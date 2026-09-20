"""火山方舟私域素材库（Assets API）客户端 + 角色单向注册流程。

火山素材管理接口走标准 OpenAPI 网关（open.volcengineapi.com），用 **AK/SK V4 签名**
（HMAC-SHA256），与模型推理用的 ARK Bearer API Key 是两套凭证。签名算法照搬火山官方
Python 示例（docs 6369/67269）；服务名 ark、版本 2024-01-01、region cn-beijing。

对接口只封装角色注册所需的最小集：CreateAssetGroup / CreateAsset / GetAsset / 删除。
只上传图片（AssetType=Image）；单向：本地建角色 → 推火山 → 轮询 Active → 回写，不反向同步。
"""
import asyncio
import datetime
import hashlib
import hmac
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import asyncpg
import httpx

from ..settings import settings

log = logging.getLogger("ark_assets")

_ALGORITHM = "HMAC-SHA256"
_CONTENT_TYPE = "application/json"


def is_configured() -> bool:
    """未配 AK/SK 时整个注册链路应优雅跳过（本地无凭证也能跑其它功能）。"""
    return bool(settings.VOLC_AK and settings.VOLC_SK)


# ═══════════ 火山 V4 签名（照搬官方 Python 示例）═══════════

def _hmac(key: bytes, content: str) -> bytes:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _norm_query(params: dict[str, str]) -> str:
    # 键按 ASCII 升序；键值按 RFC3986 编码（safe="-_.~"）；+ 换成 %20
    parts = []
    for k in sorted(params):
        parts.append(f"{quote(k, safe='-_.~')}={quote(params[k], safe='-_.~')}")
    return "&".join(parts).replace("+", "%20")


def _signed_request(action: str, body_str: str) -> tuple[str, dict[str, str]]:
    """返回 (完整 url, 请求头)。body_str 必须与实际发送的字节完全一致。"""
    host = settings.VOLC_ASSET_HOST
    region = settings.VOLC_ASSET_REGION
    service = settings.VOLC_ASSET_SERVICE
    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    x_content_sha256 = _sha256_hex(body_str)

    query = _norm_query({"Action": action, "Version": settings.VOLC_ASSET_VERSION})

    # 规范请求：header 按名称升序（content-type;host;x-content-sha256;x-date）
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_headers = (
        f"content-type:{_CONTENT_TYPE}\n"
        f"host:{host}\n"
        f"x-content-sha256:{x_content_sha256}\n"
        f"x-date:{x_date}\n"
    )
    canonical_request = "\n".join([
        "POST", "/", query, canonical_headers, signed_headers, x_content_sha256,
    ])

    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join([
        _ALGORITHM, x_date, credential_scope, _sha256_hex(canonical_request),
    ])

    k_date = _hmac(settings.VOLC_SK.encode("utf-8"), short_date)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{_ALGORITHM} Credential={settings.VOLC_AK}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": x_content_sha256,
        "Content-Type": _CONTENT_TYPE,
        "Authorization": authorization,
    }
    # 必须发送与签名一致的 query 串，故直接拼进 URL（不让 httpx 重新编码）
    url = f"https://{host}/?{query}"
    return url, headers


async def _call(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """调用一个 Assets API，返回 Result 字段（火山成功响应形如 {"ResponseMetadata":..,"Result":..}）。"""
    if not is_configured():
        raise RuntimeError("未配置 VOLC_AK / VOLC_SK，无法调用火山素材库")
    body_str = json.dumps(payload, ensure_ascii=False)
    url, headers = _signed_request(action, body_str)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        r = await client.post(url, content=body_str.encode("utf-8"), headers=headers)
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"{action} 响应非 JSON（HTTP {r.status_code}）: {r.text[:200]}")
    meta = (data.get("ResponseMetadata") or {}) if isinstance(data, dict) else {}
    err = meta.get("Error")
    if err or r.status_code >= 400:
        msg = (err or {}).get("Message") or r.text[:200]
        code = (err or {}).get("Code") or r.status_code
        raise RuntimeError(f"{action} 失败[{code}]: {msg}")
    return data.get("Result") or {}


# ═══════════ 接口封装 ═══════════

# 火山 Name/Description 有长度上限，作品角色的 description 常是整段英文外貌提示词，超长会被拒
# （线上实测"描述过长"）。提交前统一强制截断，保证简洁且不触限；宁可短，描述对素材匹配无功能作用（按名匹配）。
_NAME_MAX = 60
_DESC_MAX = 120


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


async def create_asset_group(name: str, description: str, project: str) -> str:
    name = _clip(name, _NAME_MAX)
    res = await _call("CreateAssetGroup", {
        "Name": name, "Description": _clip(description, _DESC_MAX) or name,
        "GroupType": "AIGC", "ProjectName": project,
    })
    gid = res.get("Id")
    if not gid:
        raise RuntimeError(f"CreateAssetGroup 未返回 Id: {res}")
    return gid


async def create_asset(group_id: str, url: str, project: str,
                       asset_type: str = "Image", name: str = "") -> str:
    res = await _call("CreateAsset", {
        "GroupId": group_id, "URL": url, "AssetType": asset_type,
        "Name": _clip(name, _NAME_MAX), "ProjectName": project,
    })
    aid = res.get("Id")
    if not aid:
        raise RuntimeError(f"CreateAsset 未返回 Id: {res}")
    return aid


async def get_asset(asset_id: str, project: str) -> dict[str, Any]:
    return await _call("GetAsset", {"Id": asset_id, "ProjectName": project})


async def delete_asset(asset_id: str, project: str) -> None:
    await _call("DeleteAsset", {"Id": asset_id, "ProjectName": project})


async def delete_asset_group(group_id: str, project: str) -> None:
    await _call("DeleteAssetGroup", {"Id": group_id, "ProjectName": project})


# ═══════════ 角色单向注册流程 ═══════════

_POLL_INTERVAL_S = 5
_POLL_TIMEOUT_S = 240  # CreateAsset 异步无 SLA，最多轮询 4 分钟


async def _set_status(pool: asyncpg.Pool, char_id: int, *, status: str,
                      group_id: str | None = None, asset_id: str | None = None,
                      error: str = "") -> None:
    await pool.execute(
        """UPDATE ark_characters SET
               ark_status=$2,
               ark_group_id=COALESCE($3, ark_group_id),
               ark_asset_id=COALESCE($4, ark_asset_id),
               ark_error=$5, updated_at=now()
           WHERE id=$1""",
        char_id, status, group_id, asset_id, error[:500],
    )


async def register_character(pool: asyncpg.Pool, char_id: int) -> None:
    """把一个角色的形象图单向注册进火山素材库，并把状态/asset_id 回写库。

    幂等：复用已建的 Asset Group（重试注册时不重复建组）。失败只落 ark_status=failed，
    不抛给上层（后台任务）。
    """
    row = await pool.fetchrow("SELECT * FROM ark_characters WHERE id=$1", char_id)
    if not row:
        return
    if not is_configured():
        await _set_status(pool, char_id, status="failed", error="未配置 VOLC_AK/VOLC_SK")
        return
    if not row["image_url"]:
        await _set_status(pool, char_id, status="failed", error="缺少形象图，无法入库")
        return

    project = row["ark_project"] or settings.ARK_PROJECT_NAME
    try:
        await _set_status(pool, char_id, status="processing", error="")
        group_id = row["ark_group_id"] or await create_asset_group(
            row["name"], row["description"], project)
        asset_id = await create_asset(
            group_id, row["image_url"], project, "Image", row["name"])
        await _set_status(pool, char_id, status="processing",
                          group_id=group_id, asset_id=asset_id)

        # 轮询至 Active/Failed
        waited = 0
        while waited < _POLL_TIMEOUT_S:
            await asyncio.sleep(_POLL_INTERVAL_S)
            waited += _POLL_INTERVAL_S
            info = await get_asset(asset_id, project)
            st = (info.get("Status") or "").lower()
            if st == "active":
                await _set_status(pool, char_id, status="active",
                                  group_id=group_id, asset_id=asset_id)
                log.info("角色 %s 入库成功 asset=%s", char_id, asset_id)
                return
            if st == "failed":
                await _set_status(pool, char_id, status="failed",
                                  group_id=group_id, asset_id=asset_id,
                                  error="火山一致性/审核校验未通过")
                return
        await _set_status(pool, char_id, status="failed", group_id=group_id,
                          asset_id=asset_id, error="入库超时（火山仍在处理，可稍后重试）")
    except Exception as e:  # noqa: BLE001 — 后台任务：失败只落库不抛
        log.warning("角色 %s 注册失败: %s", char_id, e)
        await _set_status(pool, char_id, status="failed", error=str(e))


def spawn_register(pool: asyncpg.Pool, char_id: int) -> None:
    """fire-and-forget 后台注册；异常兜底避免 task 静默吞掉。"""
    task = asyncio.create_task(register_character(pool, char_id))

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            log.warning("register_character task 异常: %s", exc)

    task.add_done_callback(_done)


# ═══════════ 生成侧：把角色参考图换成 asset:// 可信素材 ═══════════

def _bare(name: str) -> str:
    """去掉括注/两端空白，取基名（"沉默老船长（黑衣人）" → "沉默老船长"）。"""
    return re.split(r"[（(]", (name or "").strip())[0].strip()


def _ident_match(a: str, b: str) -> bool:
    """两个角色名是否同一身份：精确 / 去括注精确 / 短名(≥2字)被长名包含。"""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    ba, bb = _bare(a), _bare(b)
    if ba and bb and ba == bb:
        return True
    short, long_ = (ba, bb) if len(ba) <= len(bb) else (bb, ba)
    return len(short) >= 2 and short in long_


async def resolve_asset_refs(
    pool: asyncpg.Pool, reference_images: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """把角色类参考图的 url 换成 asset://<asset_id>（该角色在角色库已 Active 时）。

    解析优先用参考图携带的 **element_id 来源字段**（storyboard 装配层写入）：按该要素的项目
    精确圈定候选 ark_characters（work 档同项目，system 档 source_project_id 为空视为全局可用），
    再按要素原名匹配——治旧「按名全局模糊匹配」的两个坑：①不按项目过滤会跨项目同名错配
    ②子串模糊匹配会跨角色误命中。无 element_id 的老数据回退全局按名匹配（向后兼容）。

    命中后**去掉 element_id 来源字段**（它不是火山字段，提交时不下发）；未命中/未 Active 的
    保持原裸 URL 回退。仅应在 ARK + Seedance 2.0 路径调用（asset:// 只在 2.0 生效）。返回新列表。
    """
    if not reference_images:
        return reference_images
    want = [r for r in reference_images
            if r.get("kind") == "character" and (r.get("element_id") or r.get("name"))]
    if not want:
        return reference_images
    rows = await pool.fetch(
        "SELECT id, name, source_project_id, ark_asset_id FROM ark_characters "
        "WHERE ark_status='active' AND ark_asset_id <> ''")
    if not rows:
        return reference_images
    # element_id → (project_id, 要素原名)：一次批量查，供按项目圈定候选
    eids = [r["element_id"] for r in want if r.get("element_id")]
    elem_by_id: dict[int, tuple[int, str]] = {}
    if eids:
        for row in await pool.fetch(
            "SELECT id, project_id, name FROM content_elements WHERE id = ANY($1)", eids
        ):
            elem_by_id[row["id"]] = (row["project_id"], row["name"])

    def _match(rows_: list[Any], name: str) -> Any | None:
        return next((x for x in rows_ if (x["name"] or "").strip() == (name or "").strip()), None) \
            or next((x for x in rows_ if _ident_match(name, x["name"])), None)

    def _find(ref: dict[str, Any]) -> Any | None:
        eid = ref.get("element_id")
        if eid and eid in elem_by_id:
            pid, ename = elem_by_id[eid]
            # 按项目圈定：同项目 work 档 + 无归属项目的 system 档（全局可复用）
            cands = [x for x in rows if x["source_project_id"] in (pid, None)]
            return _match(cands, ename)
        # 无 element_id（老 meta 未重装配）：回退全局按名匹配
        return _match(list(rows), ref.get("name") or "")

    out: list[dict[str, Any]] = []
    for r in reference_images:
        if r.get("kind") == "character":
            explicit_id = r.get("identity_character_id")
            hit = next((x for x in rows if explicit_id and x["id"] == explicit_id), None)
            if not hit:
                hit = _find(r)
            r = {k: v for k, v in r.items()
                 if k not in ("element_id", "identity_character_id")}  # 提交前去掉来源字段
            if hit:
                log.info("角色「%s」改用火山可信素材 asset://%s", r.get("name"), hit["ark_asset_id"])
                r = {**r, "url": f"asset://{hit['ark_asset_id']}"}
        out.append(r)
    return out
