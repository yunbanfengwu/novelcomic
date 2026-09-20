"""分镜 API：拆分镜 / 提示词生成(含质检) / 首帧 / 异步视频 / SSE 事件流。

2026-07-11 起全部生成走统一管线（services/flow.py + steps.py）：
API 只负责组 payload + 入队，前置守卫与质检在 worker 侧 Step.before/next 完成。
2026-07-13 起首帧/视频走 flow.enqueue_with_deps（依赖 DAG）：缺提示词/首帧不再 400 拦截，
而是逐级向上自动派发生产者子任务（gen_video→gen_keyframe→gen_prompts），
子任务完成逐级回调放行父任务。优先级：单镜手点=10 > 拆镜=5 > 整章批量=0。
"""
import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..db import get_pool
from ..services import events, flow, production_canvas, volumes

router = APIRouter(prefix="/api/projects/{project_id}", tags=["shots"])


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


@router.post("/chapters/{node_id}/storyboard")
async def breakdown(project_id: int, node_id: int):
    """章节→动态**粗拆分镜骨架**（两阶段拆镜第一阶段，异步任务，无正文时按目录故事线直接拆）。
    只出 骨架+景别+时长 的小 JSON（避免整章全字段撑爆 token 被截断）；拆完自动串出详细分镜
    展开任务（按板≤16镜）→ 再为每镜串 gen_prompts（装配+九维质检）。
    宫格总览图不再自动生成（2026-07-12：总图效果不佳，改为手动触发）。"""
    return await flow.enqueue(
        get_pool(), kind="breakdown_chapter", project_id=project_id, node_id=node_id, priority=5,
    )


class EpisodeFlashIn(BaseModel):
    draft_id: str | None = None


class EpisodeFlashPromptIn(BaseModel):
    mode: Literal[
        "flash20", "sampled_story", "timeline_supercut",
        "adaptive_groups", "adaptive_duration", "slate_marked",
    ] = "flash20"
    source_minutes: int | None = None


@router.post("/chapters/{node_id}/episode-flash/prompt")
async def episode_flash_prompt(project_id: int, node_id: int,
                               body: EpisodeFlashPromptIn | None = None):
    """阶段一：生成并永久保留分段母带提示词；此时不生成视频、不抽帧。"""
    from ..services import episode_adaptive, episode_flash

    # episode_adaptive_duration is added as an isolated experiment service so the
    # three historical fixed-5s modes never change semantics.
    from ..services import episode_adaptive_duration

    pool = get_pool()
    project = await pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    chapter = await pool.fetchrow(
        "SELECT * FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        node_id, project_id)
    if not project or not chapter:
        raise HTTPException(404, "项目或剧集不存在")
    mode = body.mode if body else episode_flash.MODE_FLASH20
    if mode == "slate_marked":
        raise HTTPException(
            410,
            "黑屏镜号板实验已停止，不再生成新的提示词；历史草稿、母带和分镜仅保留查看",
        )
    source_minutes = body.source_minutes if body and body.source_minutes else (
        10 if mode == episode_flash.MODE_SAMPLED_STORY else
        6 if mode in (
            episode_flash.MODE_TIMELINE_SUPERCUT,
            episode_adaptive.MODE_ADAPTIVE_GROUPS,
            episode_adaptive_duration.MODE_ADAPTIVE_DURATION,
            "slate_marked",
        ) else 8)
    if not 6 <= source_minutes <= 10:
        raise HTTPException(422, "源剧情时长必须在6至10分钟之间")
    try:
        if mode == episode_adaptive.MODE_ADAPTIVE_GROUPS:
            distilled = await episode_adaptive.distill(
                pool, project, chapter, source_minutes=source_minutes)
        elif mode in (episode_adaptive_duration.MODE_ADAPTIVE_DURATION, "slate_marked"):
            distilled = await episode_adaptive_duration.distill(
                pool, project, chapter, source_minutes=source_minutes)
            if mode == "slate_marked":
                distilled["mode"] = mode
                distilled["prompt"] = (
                    "【确定性后期实验】生成原始母带后，服务端将在每个计划切换点插入恰好一帧纯黑镜号板；"
                    "原始母带与标记母带都永久保留。\n" + distilled["prompt"])
        else:
            distilled = await episode_flash.distill(
                pool, project, chapter, mode=mode, source_minutes=source_minutes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"分镜母带提示词生成失败：{str(exc)[:300]}")
    draft = {
        "id": uuid4().hex[:12], "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft", "prompt": distilled["prompt"], "beats": distilled["beats"],
        "refs": distilled["refs"],
        "duration_s": distilled.get("duration_s", episode_flash.TOTAL_S),
        "shot_count": distilled.get("shot_count", episode_flash.BEAT_COUNT), "mode": mode,
        "source_minutes": source_minutes,
        "resolution": distilled.get("resolution"),
        **({"groups": distilled["groups"]} if distilled.get("groups") else {}),
        **({"max_group_beats": distilled["max_group_beats"]}
           if distilled.get("max_group_beats") else {}),
    }
    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter_meta = _jsonb(await conn.fetchval(
                "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", node_id))
            drafts = list(chapter_meta.get("episode_flash_drafts") or [])
            drafts.append(draft)
            chapter_meta["episode_flash_drafts"] = drafts
            chapter_meta["episode_flash_draft"] = draft
            await conn.execute(
                "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() WHERE id=$1",
                node_id, json.dumps(chapter_meta, ensure_ascii=False))
    return draft


@router.get("/chapters/{node_id}/episode-flash")
async def get_episode_flash(project_id: int, node_id: int):
    """返回本集所有母带实验批次；测试数据只标状态，永不从该接口隐藏。"""
    pool = get_pool()
    chapter_meta = _jsonb(await pool.fetchval(
        "SELECT meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        node_id, project_id))
    masters = await pool.fetch(
        "SELECT id,url,meta,created_at FROM content_attachments "
        "WHERE project_id=$1 AND node_id=$2 AND meta->>'type'='episode_flash_master' "
        "ORDER BY id", project_id, node_id)
    shots = await pool.fetch(
        "SELECT id,deleted_at,meta FROM content_nodes WHERE project_id=$1 AND parent_id=$2 "
        "AND kind='shot' AND meta->>'keyframe_source'='episode_flash_extract' ORDER BY seq",
        project_id, node_id)
    extracted_rows = await pool.fetch(
        "SELECT id,url,meta,created_at FROM content_attachments "
        "WHERE project_id=$1 AND node_id=$2 AND kind='image' "
        "AND meta->>'type'='episode_flash_extracted_frame' ORDER BY id",
        project_id, node_id)
    timeline_rows = await pool.fetch(
        "SELECT id,meta,created_at FROM content_attachments "
        "WHERE project_id=$1 AND node_id=$2 AND kind='data' "
        "AND meta->>'type'='episode_preview_timeline' ORDER BY id",
        project_id, node_id)
    counts: dict[str, dict[str, int]] = {}
    legacy_count = 0
    for shot in shots:
        meta = _jsonb(shot["meta"])
        batch = str(meta.get("episode_flash_batch") or "")
        if not batch:
            legacy_count += 1
            continue
        item = counts.setdefault(batch, {"frames": 0, "visible_frames": 0})
        item["frames"] += 1
        if shot["deleted_at"] is None:
            item["visible_frames"] += 1
    extracted_by_batch: dict[str, list[dict[str, Any]]] = {}
    for frame_row in extracted_rows:
        frame_meta = _jsonb(frame_row["meta"])
        frame_batch = str(frame_meta.get("batch_id") or "")
        if not frame_batch:
            continue
        extracted_by_batch.setdefault(frame_batch, []).append({
            "attachment_id": frame_row["id"], "url": frame_row["url"],
            "beat_no": frame_meta.get("beat_no"), "at_s": frame_meta.get("at_s"),
            "run_id": frame_meta.get("run_id"), "width": frame_meta.get("width"),
            "height": frame_meta.get("height"), "created_at": frame_row["created_at"],
        })
    timeline_by_source: dict[int, dict[str, Any]] = {}
    timeline_counts: dict[int, int] = {}
    for timeline_row in timeline_rows:
        timeline_meta = _jsonb(timeline_row["meta"])
        try:
            source_id = int(timeline_meta.get("source_attachment_id") or 0)
        except (TypeError, ValueError):
            continue
        if source_id <= 0:
            continue
        timeline_counts[source_id] = timeline_counts.get(source_id, 0) + 1
        timeline_by_source[source_id] = {
            **timeline_meta,
            "attachment_id": timeline_row["id"],
            "created_at": timeline_row["created_at"],
        }
    batches = []
    for i, row in enumerate(masters):
        meta = _jsonb(row["meta"])
        batch = str(meta.get("batch_id") or row["id"])
        count = counts.get(batch, {})
        extracted_frames = extracted_by_batch.get(batch, [])
        if i == 0 and legacy_count and not count:
            count = {"frames": legacy_count, "visible_frames": legacy_count}
        batches.append({
            "id": batch, "attachment_id": row["id"], "video_url": row["url"],
            "created_at": row["created_at"], "status": meta.get("status") or (
                "invalid" if meta.get("invalid_experiment") else "done"),
            "valid": not bool(meta.get("invalid_experiment")),
            "note": meta.get("reason") or meta.get("note"),
            "frames": max(
                int(count.get("frames", 0)), len(extracted_frames), int(meta.get("frames") or 0)),
            "visible_frames": max(int(count.get("visible_frames", 0)), len(extracted_frames)),
            "refs": meta.get("refs") or [],
            "prompt": meta.get("prompt") or "", "beats": meta.get("beats") or [],
            "draft_id": meta.get("draft_id"), "mode": meta.get("mode") or "flash20",
            "source_minutes": meta.get("source_minutes") or 8,
            "resolution": meta.get("resolution"),
            "duration_s": meta.get("duration_s") or 5,
            "shot_count": meta.get("shot_count") or len(meta.get("beats") or []),
            "groups": meta.get("groups") or [],
            "markers": meta.get("markers") or [],
            "raw_attachment_id": meta.get("raw_attachment_id"),
            "raw_video_url": meta.get("raw_video_url"),
            "split_runs": meta.get("split_runs") or [],
            "split_method": meta.get("split_method"),
            "visual_slate_detection": meta.get("visual_slate_detection"),
            "total_extracted_frames": meta.get("total_extracted_frames") or 0,
            "extracted_frames": extracted_frames,
            "frame_extract_runs": meta.get("frame_extract_runs") or [],
            "timeline": timeline_by_source.get(int(row["id"])),
            "timeline_version_count": timeline_counts.get(int(row["id"]), 0),
        })
    drafts = list(chapter_meta.get("episode_flash_drafts") or [])
    return {"batches": batches, "latest": batches[-1] if batches else None,
            "draft": chapter_meta.get("episode_flash_draft"), "drafts": drafts}


class EpisodeFlashReviewIn(BaseModel):
    status: Literal["awaiting_review", "invalid"]
    note: str | None = None


@router.patch("/chapters/{node_id}/episode-flash/{attachment_id}")
async def review_episode_flash(project_id: int, node_id: int, attachment_id: int,
                               body: EpisodeFlashReviewIn):
    """只更新实验批次评审状态；附件、提示词及历史批次永不删除。"""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id,meta FROM content_attachments WHERE id=$1 AND project_id=$2 AND node_id=$3 "
        "AND meta->>'type'='episode_flash_master'", attachment_id, project_id, node_id)
    if not row:
        raise HTTPException(404, "母带实验批次不存在")
    patch = {"status": body.status, "note": body.note or ""}
    if body.status == "invalid":
        patch["invalid_experiment"] = True
        patch["reason"] = body.note or "人工审核未通过"
    else:
        patch["invalid_experiment"] = False
    batch_id = str(_jsonb(row["meta"]).get("batch_id") or attachment_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                attachment_id, json.dumps(patch, ensure_ascii=False))
            chapter_meta = _jsonb(await conn.fetchval(
                "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", node_id))
            for batch in chapter_meta.get("episode_flash_batches") or []:
                if str(batch.get("id")) == batch_id:
                    batch["status"] = body.status
                    batch["note"] = body.note or ""
            latest = chapter_meta.get("episode_flash") or {}
            if str(latest.get("id")) == batch_id:
                latest["status"] = body.status
                latest["note"] = body.note or ""
            await conn.execute(
                "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() WHERE id=$1",
                node_id, json.dumps(chapter_meta, ensure_ascii=False))
    return {"ok": True, "batch_id": batch_id, "status": body.status, "preserved": True}


@router.post("/chapters/{node_id}/episode-flash/master")
async def generate_episode_flash_master(project_id: int, node_id: int, body: EpisodeFlashIn | None = None):
    """阶段二：只生成并保留整集闪回母带，待人工审核；不抽帧、不创建分镜。"""
    from .. import media
    from ..services import (
        asset_gen, episode_adaptive, episode_adaptive_duration, episode_flash,
        video_concat, video_slate,
    )

    pool = get_pool()
    project = await pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    chapter = await pool.fetchrow(
        "SELECT * FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        node_id, project_id)
    if not project or not chapter:
        raise HTTPException(404, "项目或剧集不存在")
    # 阶段二只能消费阶段一落库的服务端草稿；不信任客户端传入的 prompt/beats/refs。
    chapter_meta = _jsonb(chapter["meta"])
    drafts = list(chapter_meta.get("episode_flash_drafts") or [])
    wanted = body.draft_id if body and body.draft_id else (
        (chapter_meta.get("episode_flash_draft") or {}).get("id"))
    distilled = next((draft for draft in drafts if draft.get("id") == wanted), None)
    if not distilled:
        raise HTTPException(409, "请先生成母带提示词，再依据该提示词生成母带视频")
    mode = distilled.get("mode") or episode_flash.MODE_FLASH20
    if mode == "slate_marked":
        raise HTTPException(
            409,
            "黑屏镜号板实验已停止；历史 slate_marked 草稿仅供查看，不能再次生成母带",
        )
    beats = list(distilled.get("beats") or [])
    if mode == episode_adaptive.MODE_ADAPTIVE_GROUPS:
        groups = list(distilled.get("groups") or [])
        flat = [beat for group in groups for beat in (group.get("beats") or [])]
        if not groups or len(flat) != len(beats):
            raise HTTPException(409, "当前自适应分组草稿结构不完整，请重新生成提示词")
        for index, group in enumerate(groups, 1):
            count = len(group.get("beats") or [])
            if not 1 <= count <= episode_adaptive.MAX_GROUP_BEATS:
                raise HTTPException(
                    409, f"第{index}组有{count}次切换，超过硬上限{episode_adaptive.MAX_GROUP_BEATS}次")
            if int(group.get("duration_s") or 0) != episode_adaptive.duration_for_beats(count):
                raise HTTPException(409, f"第{index}组时长与容量公式不一致，请重新生成提示词")
    elif mode in (episode_adaptive_duration.MODE_ADAPTIVE_DURATION, "slate_marked"):
        expected_duration = episode_adaptive_duration.duration_for_beats(len(beats))
        if int(distilled.get("duration_s") or 0) != expected_duration:
            raise HTTPException(409, "动态时长草稿与5秒/15次容量公式不一致，请重新生成提示词")
    elif len(beats) != episode_flash.BEAT_COUNT:
        raise HTTPException(409, f"当前母带提示词不是{episode_flash.BEAT_COUNT}段，请重新生成")
    prompt = distilled["prompt"].strip()
    available_refs = await pool.fetch(
        "SELECT id,name,kind,meta->>'sheet_url' AS url FROM content_elements "
        "WHERE project_id=$1 AND kind IN ('character','scene') "
        "AND coalesce(meta->>'sheet_url','') <> ''", project_id)
    allowed_refs = {(r["name"], r["kind"], r["url"]) for r in available_refs}
    allowed_by_id = {r["id"]: (r["name"], r["kind"], r["url"]) for r in available_refs}
    stored_refs = list(distilled["refs"])
    refs = [r for r in stored_refs if (
        (r.get("element_id") in allowed_by_id and
         allowed_by_id[r["element_id"]] == (r.get("name"), r.get("kind"), r.get("url")))
        if r.get("element_id") else
        (r.get("name"), r.get("kind"), r.get("url")) in allowed_refs)]
    if not refs or len(refs) != len(stored_refs):
        raise HTTPException(409, "母带参考图已缺失或发生变化，为防止@图片编号漂移，请重新生成提示词")
    if not await media.video_reference_images_supported():
        raise HTTPException(409, "当前视频模型不支持@图片参考，请先切换到支持reference_image的Seedance 2.x")
    ref_cap = await media.video_reference_image_cap()
    if len(refs) > ref_cap:
        raise HTTPException(409, f"当前视频模型最多接收{ref_cap}张参考图，请重新生成提示词")
    ratio = "9:16" if _jsonb(project["config"]).get("aspect_ratio") == "9:16" else "16:9"
    generated_groups: list[dict[str, Any]] = []
    raw_attachment_id: int | None = None
    raw_video_url: str | None = None
    markers: list[dict[str, Any]] = []
    if mode == episode_adaptive.MODE_ADAPTIVE_GROUPS:
        run_id = uuid4().hex[:12]

        async def generate_group(group: dict[str, Any]) -> dict[str, Any]:
            group_no = int(group["no"])
            group_name = (
                f"第{chapter['seq']}集·自适应组{group_no}/{len(groups)}·"
                f"{len(group['beats'])}次·{group['duration_s']}秒")
            audit_token = media.GEN_AUDIT.set({
                "project_id": project_id, "node_id": node_id, "chapter_id": node_id,
                "chapter_title": chapter["title"], "kind": "gen_episode_flash_group",
                "source": f"project_{project_id}_{chapter['seq']}_adaptive_group_{group_no}",
            })
            try:
                asset = await asset_gen.generate_video_asset(
                    pool, project_id, str(group["prompt"]), refs, ratio=ratio,
                    duration=int(group["duration_s"]), store_dir="episode_flash",
                    meta_type="episode_flash_group", display_name=group_name,
                    node_id=node_id, resolution=distilled.get("resolution"))
                group_meta = {
                    "run_id": run_id, "draft_id": distilled["id"],
                    "group_no": group_no, "group_count": len(groups),
                    "shot_count": len(group["beats"]),
                    "duration_s": int(group["duration_s"]),
                    "prompt": group["prompt"], "beats": group["beats"],
                    "refs": refs, "status": "done",
                }
                await pool.execute(
                    "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                    asset["id"], json.dumps(group_meta, ensure_ascii=False))
                return {**group, "attachment_id": asset["id"], "video_url": asset["url"]}
            finally:
                media.GEN_AUDIT.reset(audit_token)

        results = await asyncio.gather(
            *(generate_group(group) for group in groups), return_exceptions=True)
        errors = [str(result) for result in results if isinstance(result, BaseException)]
        generated_groups = [result for result in results if isinstance(result, dict)]
        if errors:
            preserved = ",".join(str(group["attachment_id"]) for group in generated_groups) or "无"
            raise HTTPException(
                502, f"自适应组视频部分生成失败；已成功的组附件永久保留({preserved})：{errors[0][:220]}")
        generated_groups.sort(key=lambda group: int(group["no"]))
        master_name = (
            f"第{chapter['seq']}集·自适应{len(generated_groups)}组·"
            f"{len(beats)}次·{distilled['duration_s']}秒拼接母带")
        try:
            master = await video_concat.concat_video_attachments(
                pool, project_id, node_id,
                [{"id": group["attachment_id"], "url": group["video_url"],
                  "duration_s": int(group["duration_s"])} for group in generated_groups],
                ratio=ratio, display_name=master_name,
                meta={"run_id": run_id, "draft_id": distilled["id"],
                      "mode": mode, "group_count": len(generated_groups),
                      "shot_count": len(beats), "duration_s": int(distilled["duration_s"])})
        except Exception as exc:  # noqa: BLE001
            preserved = ",".join(str(group["attachment_id"]) for group in generated_groups)
            raise HTTPException(
                502, f"组视频均已永久保留({preserved})，最终拼接失败：{str(exc)[:220]}")
    else:
        duration_s = int(distilled.get("duration_s") or episode_flash.TOTAL_S)
        if mode == episode_flash.MODE_TIMELINE_SUPERCUT:
            master_name = f"第{chapter['seq']}集·480p·5秒分镜时间轴超级加速母带"
        elif mode == episode_flash.MODE_SAMPLED_STORY:
            master_name = f"第{chapter['seq']}集·5秒抽帧式超级加速母带"
        elif mode == episode_adaptive_duration.MODE_ADAPTIVE_DURATION:
            master_name = f"第{chapter['seq']}集·{len(beats)}次·{duration_s}秒动态容量母带"
        elif mode == "slate_marked":
            master_name = f"第{chapter['seq']}集·{len(beats)}次·单帧镜号板实验原片"
        else:
            master_name = f"第{chapter['seq']}集·5秒20镜超快闪回母带"
        token = media.GEN_AUDIT.set({
            "project_id": project_id, "node_id": node_id, "chapter_id": node_id,
            "chapter_title": chapter["title"], "kind": "gen_episode_flash_master",
            "source": f"project_{project_id}_{chapter['seq']}_episode_flash_master",
        })
        try:
            master = await asset_gen.generate_video_asset(
                pool, project_id, prompt, refs, ratio=ratio, duration=duration_s,
                store_dir="episode_flash",
                meta_type="episode_flash_raw" if mode == "slate_marked" else "episode_flash_master",
                display_name=master_name, node_id=node_id,
                resolution=distilled.get("resolution"))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)[:300])
        finally:
            media.GEN_AUDIT.reset(token)

        if mode == "slate_marked":
            raw_attachment_id = int(master["id"])
            raw_video_url = str(master["url"])
            await pool.execute(
                "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                raw_attachment_id,
                json.dumps({
                    "draft_id": distilled["id"], "mode": mode,
                    "duration_s": duration_s, "shot_count": len(beats),
                    "prompt": prompt, "beats": beats, "refs": refs,
                    "status": "done", "preserved": True,
                }, ensure_ascii=False))
            marked_name = (
                f"第{chapter['seq']}集·{len(beats)}次·{duration_s}秒·单帧黑场镜号板母带")
            try:
                master = await video_slate.add_one_frame_slates(
                    pool, project_id, node_id,
                    {"id": raw_attachment_id, "url": raw_video_url},
                    beats, ratio=ratio, duration_s=duration_s,
                    display_name=marked_name,
                    meta={"draft_id": distilled["id"], "mode": mode,
                          "shot_count": len(beats), "duration_s": duration_s})
                markers = list((master.get("meta") or {}).get("markers") or [])
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    502, f"原始母带附件{raw_attachment_id}已永久保留，单帧镜号板后处理失败：{str(exc)[:220]}")

    batch_id = str(master["id"])
    batch = {
        "id": batch_id, "draft_id": distilled["id"], "video_url": master["url"], "prompt": prompt,
        "beats": distilled["beats"], "refs": [
            {key: r.get(key) for key in ("element_id", "name", "kind", "url", "binding")
             if r.get(key) is not None} for r in refs],
        "frames": 0, "status": "awaiting_review", "experimental": True,
        "mode": mode,
        "source_minutes": distilled.get("source_minutes") or 8,
        "resolution": distilled.get("resolution"),
        "duration_s": int(distilled.get("duration_s") or episode_flash.TOTAL_S),
        "shot_count": len(beats),
        "groups": generated_groups,
        "markers": markers,
        "raw_attachment_id": raw_attachment_id,
        "raw_video_url": raw_video_url,
    }
    # 先把永久附件挂到章节并写入完整状态；即使随后批次索引事务失败，测试母带仍可见、可追溯。
    await pool.execute(
        "UPDATE content_attachments SET node_id=$2,meta=meta || $3::jsonb WHERE id=$1",
        master["id"], node_id,
        json.dumps({"batch_id": batch_id, "status": "awaiting_review", "frames": 0,
                    "draft_id": distilled["id"], "prompt": prompt,
                    "beats": distilled["beats"], "refs": batch["refs"],
                    "mode": batch["mode"], "source_minutes": batch["source_minutes"],
                    "resolution": batch["resolution"], "duration_s": batch["duration_s"],
                    "shot_count": batch["shot_count"], "groups": batch["groups"],
                    "markers": batch["markers"],
                    "raw_attachment_id": batch["raw_attachment_id"],
                    "raw_video_url": batch["raw_video_url"]},
                   ensure_ascii=False))
    async with pool.acquire() as conn:
        async with conn.transaction():
            chapter_meta = _jsonb(await conn.fetchval(
                "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", node_id))
            batches = list(chapter_meta.get("episode_flash_batches") or [])
            batches.append(batch)
            chapter_meta["episode_flash_batches"] = batches
            chapter_meta["episode_flash"] = batch
            await conn.execute(
                "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() WHERE id=$1",
                node_id, json.dumps(chapter_meta, ensure_ascii=False))
    return {"batch": batch, "video_url": master["url"], "prompt": prompt,
            "beats": distilled["beats"], "refs": batch["refs"],
            "groups": batch["groups"], "duration_s": batch["duration_s"],
            "markers": batch["markers"], "raw_video_url": batch["raw_video_url"]}


@router.post("/chapters/{node_id}/episode-flash/{attachment_id}/extract-frames")
async def extract_episode_flash_frames(project_id: int, node_id: int, attachment_id: int):
    """从任意实验母带按其时间表中点抽代表帧；与镜号板、正式分镜完全解耦。

    每个 beat 只抽一张图，永久挂在章节和原实验批次下。相同批次重复点击直接返回
    已有帧，不重复上传；原视频、历史批次、正式分镜均不修改或删除。
    """
    from .. import oss
    from ..services import video_frame_extract

    pool = get_pool()
    chapter = await pool.fetchval(
        "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 "
        "AND kind='chapter' AND deleted_at IS NULL", node_id, project_id)
    master = await pool.fetchrow(
        "SELECT id,url,meta FROM content_attachments "
        "WHERE id=$1 AND project_id=$2 AND node_id=$3 AND kind='video' "
        "AND meta->>'type'='episode_flash_master'",
        attachment_id, project_id, node_id)
    if not chapter or not master:
        raise HTTPException(404, "章节或实验母带不存在")
    master_meta = _jsonb(master["meta"])
    batch_id = str(master_meta.get("batch_id") or master["id"])

    async def existing_frames(conn: Any = pool) -> list[dict[str, Any]]:
        rows = await conn.fetch(
            "SELECT id,url,meta,created_at FROM content_attachments "
            "WHERE project_id=$1 AND node_id=$2 AND kind='image' "
            "AND meta->>'type'='episode_flash_extracted_frame' "
            "AND meta->>'batch_id'=$3 AND meta->>'source_attachment_id'=$4 "
            "ORDER BY (meta->>'beat_no')::int,id",
            project_id, node_id, batch_id, str(master["id"]))
        return [{
            "attachment_id": row["id"], "url": row["url"],
            "beat_no": _jsonb(row["meta"]).get("beat_no"),
            "at_s": _jsonb(row["meta"]).get("at_s"),
            "run_id": _jsonb(row["meta"]).get("run_id"),
            "width": _jsonb(row["meta"]).get("width"),
            "height": _jsonb(row["meta"]).get("height"),
            "created_at": row["created_at"],
        } for row in rows]

    existing = await existing_frames()
    if existing:
        run = next(reversed(master_meta.get("frame_extract_runs") or []), {})
        return {"frames": existing, "run": run, "idempotent": True, "preserved": True}

    beats = list(master_meta.get("beats") or [])
    if not beats:
        beats = [beat for group in (master_meta.get("groups") or [])
                 for beat in (group.get("beats") or [])]
    if not beats:
        raise HTTPException(409, "当前实验母带没有可用于抽帧的分段时间表")
    try:
        duration_s = float(master_meta.get("duration_s") or 5)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, "实验母带时长无效，无法按时间表抽帧") from exc

    run_id = uuid4().hex[:12]
    run_started = datetime.now(timezone.utc).isoformat()
    run_meta = {
        "type": "episode_flash_frame_extract_run", "run_id": run_id,
        "batch_id": batch_id, "source_attachment_id": master["id"],
        "source_video_url": master["url"], "method": "timeline_midpoint",
        "independent_of_slates": True, "status": "processing",
        "created_at": run_started, "preserved": True,
    }
    manifest = await pool.fetchrow(
        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
        "VALUES($1,$2,'data',NULL,$3::jsonb) RETURNING id",
        project_id, node_id, json.dumps(run_meta, ensure_ascii=False))
    manifest_id = int(manifest["id"])

    try:
        extracted = await video_frame_extract.extract_timeline_frames(
            str(master["url"]), beats, duration_s, width=854, height=480)
        semaphore = asyncio.Semaphore(8)

        async def store_frame(frame: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                url = await oss.store_bytes(
                    frame["jpeg_bytes"],
                    prefix=f"episode_flash_frames/{project_id}/{run_id}", ext=".jpeg")
            if not url:
                raise RuntimeError(f"关键画面{frame['beat_no']}未能永久存储")
            return {
                **{key: value for key, value in frame.items() if key != "jpeg_bytes"},
                "url": url,
            }

        stored = await asyncio.gather(*(store_frame(frame) for frame in extracted))
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({"status": "stored", "frames": stored}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({
                "status": "failed", "error": str(exc)[:500],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        raise HTTPException(502, f"实验母带抽帧失败；运行记录{manifest_id}已保留：{str(exc)[:260]}")

    saved_frames: list[dict[str, Any]] = []
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                locked_meta = _jsonb(await conn.fetchval(
                    "SELECT meta FROM content_attachments WHERE id=$1 FOR UPDATE", master["id"]))
                concurrent = await existing_frames(conn)
                if concurrent:
                    await conn.execute(
                        "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                        manifest_id, json.dumps({
                            "status": "superseded", "note": "同批次已有抽帧结果，上传文件保留在本运行清单",
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                        }, ensure_ascii=False))
                    return {"frames": concurrent,
                            "run": next(reversed(locked_meta.get("frame_extract_runs") or []), {}),
                            "idempotent": True, "preserved": True}

                for frame in stored:
                    row = await conn.fetchrow(
                        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
                        "VALUES($1,$2,'image',$3,$4::jsonb) RETURNING id,created_at",
                        project_id, node_id, frame["url"], json.dumps({
                            "type": "episode_flash_extracted_frame", "run_id": run_id,
                            "batch_id": batch_id, "source_attachment_id": master["id"],
                            "beat_no": frame["beat_no"], "at_s": frame["at_s"],
                            "width": frame["width"], "height": frame["height"],
                            "method": "timeline_midpoint", "independent_of_slates": True,
                            "preserved": True,
                        }, ensure_ascii=False))
                    saved_frames.append({
                        "attachment_id": row["id"], "url": frame["url"],
                        "beat_no": frame["beat_no"], "at_s": frame["at_s"],
                        "run_id": run_id, "width": frame["width"], "height": frame["height"],
                        "created_at": row["created_at"],
                    })

                run_summary = {
                    "run_id": run_id, "manifest_attachment_id": manifest_id,
                    "source_attachment_id": master["id"], "method": "timeline_midpoint",
                    "independent_of_slates": True, "frame_count": len(saved_frames),
                    "status": "done", "created_at": run_started,
                    "finished_at": datetime.now(timezone.utc).isoformat(), "preserved": True,
                }
                runs = list(locked_meta.get("frame_extract_runs") or [])
                runs.append(run_summary)
                locked_meta["frame_extract_runs"] = runs
                locked_meta["extracted_frame_count"] = len(saved_frames)
                locked_meta["frames"] = max(int(locked_meta.get("frames") or 0), len(saved_frames))
                if not locked_meta.get("invalid_experiment"):
                    locked_meta["status"] = "sampled"
                await conn.execute(
                    "UPDATE content_attachments SET meta=$2::jsonb WHERE id=$1",
                    master["id"], json.dumps(locked_meta, ensure_ascii=False))
                await conn.execute(
                    "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                    manifest_id, json.dumps({
                        **run_summary, "frame_attachment_ids": [f["attachment_id"] for f in saved_frames],
                    }, ensure_ascii=False))

                chapter_meta = _jsonb(await conn.fetchval(
                    "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", node_id))
                for saved_batch in chapter_meta.get("episode_flash_batches") or []:
                    if str(saved_batch.get("id")) == batch_id:
                        saved_batch["frame_extract_runs"] = runs
                        saved_batch["frames"] = max(
                            int(saved_batch.get("frames") or 0), len(saved_frames))
                        saved_batch["visible_frames"] = saved_batch["frames"]
                        if saved_batch.get("status") != "invalid":
                            saved_batch["status"] = "sampled"
                latest = chapter_meta.get("episode_flash") or {}
                if str(latest.get("id")) == batch_id:
                    latest["frame_extract_runs"] = runs
                    latest["frames"] = max(int(latest.get("frames") or 0), len(saved_frames))
                    latest["visible_frames"] = latest["frames"]
                    if latest.get("status") != "invalid":
                        latest["status"] = "sampled"
                await conn.execute(
                    "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() WHERE id=$1",
                    node_id, json.dumps(chapter_meta, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({
                "status": "failed_after_store", "error": str(exc)[:500],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        raise HTTPException(
            502, f"抽取图片均已保留在运行清单{manifest_id}，但附件落库失败：{str(exc)[:240]}")

    return {"frames": saved_frames, "run": run_summary,
            "idempotent": False, "preserved": True}


class PreviewTimelineSegmentIn(BaseModel):
    id: str
    script_event_ids: list[str]
    preview_start_s: float
    preview_end_s: float
    selected_frame_attachment_id: int | None = None
    locked: bool = False


class PreviewScriptBandIn(BaseModel):
    event_id: str
    start_s: float
    end_s: float


class PreviewTimelineSaveIn(BaseModel):
    base_attachment_id: int
    segments: list[PreviewTimelineSegmentIn]
    script_bands: list[PreviewScriptBandIn] | None = None


def _timeline_result(row: Any) -> dict[str, Any]:
    meta = _jsonb(row["meta"])
    return {**meta, "attachment_id": row["id"], "created_at": row["created_at"]}


async def _episode_preview_master(pool: Any, project_id: int, node_id: int,
                                  attachment_id: int) -> Any:
    master = await pool.fetchrow(
        "SELECT id,url,meta FROM content_attachments "
        "WHERE id=$1 AND project_id=$2 AND node_id=$3 AND kind='video' "
        "AND meta->>'type'='episode_flash_master'",
        attachment_id, project_id, node_id)
    if not master:
        raise HTTPException(404, "实验母带不存在")
    return master


async def _latest_preview_timeline(pool: Any, project_id: int, node_id: int,
                                   attachment_id: int) -> Any:
    return await pool.fetchrow(
        "SELECT id,meta,created_at FROM content_attachments "
        "WHERE project_id=$1 AND node_id=$2 AND kind='data' "
        "AND meta->>'type'='episode_preview_timeline' "
        "AND meta->>'source_attachment_id'=$3 ORDER BY id DESC LIMIT 1",
        project_id, node_id, str(attachment_id))


@router.post("/chapters/{node_id}/episode-flash/{attachment_id}/timeline")
async def create_episode_preview_timeline(project_id: int, node_id: int, attachment_id: int):
    """把任意实验母带规范化为脚本事件×预览片段双时间线。

    初始边界来自服务端保存的 beat 时间表，剧情文字只来自原始 beat/evidence；
    已存在时间线时幂等返回最新版本。所有版本均作为 data 附件永久保留。
    """
    from ..services import episode_preview_timeline

    pool = get_pool()
    chapter = await pool.fetchval(
        "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 "
        "AND kind='chapter' AND deleted_at IS NULL", node_id, project_id)
    if not chapter:
        raise HTTPException(404, "章节不存在")
    master = await _episode_preview_master(pool, project_id, node_id, attachment_id)
    existing = await _latest_preview_timeline(
        pool, project_id, node_id, attachment_id)
    if existing:
        return {"timeline": _timeline_result(existing), "idempotent": True}

    frame_rows = await pool.fetch(
        "SELECT id,url,meta FROM content_attachments "
        "WHERE project_id=$1 AND node_id=$2 AND kind='image' "
        "AND meta->>'type'='episode_flash_extracted_frame' "
        "AND meta->>'source_attachment_id'=$3 ORDER BY id",
        project_id, node_id, str(attachment_id))
    frames = [{
        "attachment_id": row["id"], "url": row["url"],
        "beat_no": _jsonb(row["meta"]).get("beat_no"),
        "at_s": _jsonb(row["meta"]).get("at_s"),
    } for row in frame_rows]
    if not frames:
        raise HTTPException(409, "请先对该实验母带执行“抽取关键帧”，再建立双时间线")

    master_meta = _jsonb(master["meta"])
    batch_id = str(master_meta.get("batch_id") or master["id"])
    try:
        timeline = episode_preview_timeline.build_initial_timeline(
            master_attachment_id=int(master["id"]),
            batch_id=batch_id,
            master_meta=master_meta,
            frames=frames,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    timeline.update({
        "timeline_id": uuid4().hex[:12],
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    row = await pool.fetchrow(
        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
        "VALUES($1,$2,'data',NULL,$3::jsonb) RETURNING id,meta,created_at",
        project_id, node_id, json.dumps(timeline, ensure_ascii=False))
    await pool.execute(
        "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
        attachment_id, json.dumps({
            "preview_timeline_attachment_id": row["id"],
            "preview_timeline_version": 1,
        }, ensure_ascii=False))
    return {"timeline": _timeline_result(row), "idempotent": False}


@router.post("/chapters/{node_id}/episode-flash/{attachment_id}/timeline/versions")
async def save_episode_preview_timeline(project_id: int, node_id: int, attachment_id: int,
                                        body: PreviewTimelineSaveIn):
    """保存双时间线校准结果为新版本；不修改、覆盖或删除旧版本。"""
    from ..services import episode_preview_timeline

    pool = get_pool()
    await _episode_preview_master(pool, project_id, node_id, attachment_id)
    latest = await _latest_preview_timeline(pool, project_id, node_id, attachment_id)
    if not latest:
        raise HTTPException(409, "请先建立双时间线")
    if int(latest["id"]) != body.base_attachment_id:
        raise HTTPException(409, "时间线已有更新，请刷新后再保存，旧版本仍已保留")
    latest_meta = _jsonb(latest["meta"])
    try:
        segments = episode_preview_timeline.normalise_edited_segments(
            latest_meta, [segment.model_dump() for segment in body.segments])
        script_bands = episode_preview_timeline.normalise_script_bands(
            latest_meta,
            [band.model_dump() for band in body.script_bands]
            if body.script_bands is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    next_meta = {
        **latest_meta,
        "segments": segments,
        "script_bands": script_bands,
        "version": int(latest_meta.get("version") or 1) + 1,
        "status": "draft",
        "parent_timeline_attachment_id": latest["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "preserved": True,
    }
    row = await pool.fetchrow(
        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
        "VALUES($1,$2,'data',NULL,$3::jsonb) RETURNING id,meta,created_at",
        project_id, node_id, json.dumps(next_meta, ensure_ascii=False))
    await pool.execute(
        "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
        attachment_id, json.dumps({
            "preview_timeline_attachment_id": row["id"],
            "preview_timeline_version": next_meta["version"],
        }, ensure_ascii=False))
    return {"timeline": _timeline_result(row), "preserved": True}


@router.post("/chapters/{node_id}/episode-flash/{attachment_id}/timeline/convert")
async def convert_episode_preview_timeline(project_id: int, node_id: int, attachment_id: int):
    """把最新对齐版本转换为正式可生成的分镜草稿。

    空章节创建新镜；已有分镜时仅在数量完全一致的情况下按顺序关联，且不覆盖原有
    剧情、提示词、首帧或视频。预览图只作为“本镜动作构图帧”额外参考，角色与场景
    身份仍由项目要素图负责。转换结果另存一个时间线版本，重复提交幂等。
    """
    from ..services.shot_ordering import SEQ_STEP

    pool = get_pool()
    master = await _episode_preview_master(pool, project_id, node_id, attachment_id)
    latest = await _latest_preview_timeline(pool, project_id, node_id, attachment_id)
    if not latest:
        raise HTTPException(409, "请先建立并校准双时间线")
    timeline = _jsonb(latest["meta"])
    segments = list(timeline.get("segments") or [])
    if not segments:
        raise HTTPException(409, "双时间线没有可转换片段")
    if any(not segment.get("selected_frame_attachment_id") for segment in segments):
        raise HTTPException(409, "每个片段都必须先选择一张动作构图参考帧")

    converted_ids = [segment.get("converted_shot_id") for segment in segments]
    if all(converted_ids):
        rows = await pool.fetch(
            "SELECT id,seq,title,summary,meta,status FROM content_nodes "
            "WHERE project_id=$1 AND parent_id=$2 AND kind='shot' "
            "AND id=ANY($3::bigint[]) ORDER BY seq",
            project_id, node_id, [int(value) for value in converted_ids])
        if len(rows) == len(segments):
            return {
                "shots": [{**dict(row), "meta": _jsonb(row["meta"])} for row in rows],
                "timeline": _timeline_result(latest),
                "idempotent": True,
            }

    selected_ids = [int(segment["selected_frame_attachment_id"]) for segment in segments]
    frame_rows = await pool.fetch(
        "SELECT id,url FROM content_attachments WHERE project_id=$1 AND node_id=$2 "
        "AND kind='image' AND id=ANY($3::bigint[]) "
        "AND meta->>'type'='episode_flash_extracted_frame'",
        project_id, node_id, selected_ids)
    frame_urls = {int(row["id"]): str(row["url"]) for row in frame_rows}
    if len(frame_urls) != len(set(selected_ids)):
        raise HTTPException(409, "部分已选参考帧已不可用，原时间线版本仍保留")

    master_meta = _jsonb(master["meta"])
    master_refs = [ref for ref in (master_meta.get("refs") or [])
                   if isinstance(ref, dict) and ref.get("url")]
    shot_rows: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.fetchval(
                "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 "
                "AND kind='chapter' FOR UPDATE", node_id, project_id)
            current_latest_id = await conn.fetchval(
                "SELECT id FROM content_attachments WHERE project_id=$1 AND node_id=$2 "
                "AND kind='data' AND meta->>'type'='episode_preview_timeline' "
                "AND meta->>'source_attachment_id'=$3 ORDER BY id DESC LIMIT 1 FOR UPDATE",
                project_id, node_id, str(attachment_id))
            if int(current_latest_id or 0) != int(latest["id"]):
                raise HTTPException(409, "时间线已有更新，请刷新后再转换")

            active = await conn.fetch(
                "SELECT id,seq,title,summary,meta,status FROM content_nodes "
                "WHERE project_id=$1 AND parent_id=$2 AND kind='shot' "
                "AND deleted_at IS NULL ORDER BY seq FOR UPDATE",
                project_id, node_id)
            if active and len(active) != len(segments):
                raise HTTPException(
                    409,
                    f"本章已有{len(active)}个分镜，与当前{len(segments)}个片段数量不一致；"
                    "为保护现有分镜，系统未自动覆盖",
                )

            all_shots = await conn.fetch(
                "SELECT seq,meta FROM content_nodes WHERE project_id=$1 AND parent_id=$2 "
                "AND kind='shot' ORDER BY seq", project_id, node_id)
            max_seq = max((int(row["seq"]) for row in all_shots), default=0)
            max_shot_no = 0
            for row in all_shots:
                try:
                    max_shot_no = max(
                        max_shot_no, math.ceil(float(_jsonb(row["meta"]).get("shot_no") or 0)))
                except (TypeError, ValueError):
                    continue

            scene_seg = 0
            previous_scene = None
            for index, segment in enumerate(segments):
                selected_id = int(segment["selected_frame_attachment_id"])
                selected_url = frame_urls[selected_id]
                characters = [str(name) for name in segment.get("characters") or [] if name]
                scene = str(segment.get("scene") or "")
                selected_refs = [
                    ref for ref in master_refs
                    if ref.get("name") in characters
                    or (ref.get("kind") == "scene" and str(ref.get("name") or "") in scene)
                ]
                element_ids = [int(ref["element_id"]) for ref in selected_refs
                               if ref.get("element_id") is not None]
                reference_images = [
                    {key: ref.get(key) for key in ("name", "kind", "url")}
                    for ref in selected_refs
                ]
                action_ref = {
                    "name": "本镜动作构图帧",
                    "kind": "preview_action",
                    "url": selected_url,
                }
                link_meta = {
                    "timeline_id": timeline.get("timeline_id"),
                    "timeline_attachment_id": latest["id"],
                    "timeline_version": timeline.get("version"),
                    "master_attachment_id": attachment_id,
                    "batch_id": timeline.get("batch_id"),
                    "segment_id": segment.get("id"),
                    "script_event_ids": segment.get("script_event_ids") or [],
                    "beat_nos": segment.get("beat_nos") or [],
                    "preview_start_s": segment.get("preview_start_s"),
                    "preview_end_s": segment.get("preview_end_s"),
                    "selected_frame_attachment_id": selected_id,
                    "selected_frame_url": selected_url,
                    "script_evidence": segment.get("evidence") or "",
                    "preserved": True,
                }

                if active:
                    row = active[index]
                    shot_meta = _jsonb(row["meta"])
                    extra_refs = [
                        ref for ref in (shot_meta.get("extra_refs") or [])
                        if ref.get("name") != action_ref["name"]
                    ]
                    extra_refs.append(action_ref)
                    links = list(shot_meta.get("preview_timeline_links") or [])
                    links.append(link_meta)
                    shot_meta.update({
                        "extra_refs": extra_refs,
                        "preview_action_ref": action_ref,
                        "preview_timeline_links": links,
                        "preview_prompt_refresh_required": True,
                    })
                    updated = await conn.fetchrow(
                        "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() "
                        "WHERE id=$1 RETURNING id,seq,title,summary,meta,status",
                        row["id"], json.dumps(shot_meta, ensure_ascii=False))
                    shot_rows.append({**dict(updated), "meta": shot_meta})
                    shot_id = int(row["id"])
                else:
                    if index == 0 or scene != previous_scene:
                        scene_seg += 1
                        previous_scene = scene
                    shot_no = max_shot_no + index + 1
                    shot_meta = {
                        "shot_no": shot_no,
                        "scene": scene,
                        "scene_element": next((
                            str(ref.get("name")) for ref in selected_refs
                            if ref.get("kind") == "scene"
                        ), scene),
                        "scene_seg": scene_seg,
                        "scale": segment.get("shot_size") or "中景",
                        "duration_s": 5,
                        "action": segment.get("picture") or "",
                        "dialogue": "无",
                        "characters": characters,
                        "element_ids": element_ids,
                        "reference_images": reference_images,
                        "reference_urls": [ref.get("url") for ref in reference_images],
                        "extra_refs": [action_ref],
                        "preview_action_ref": action_ref,
                        "preview_timeline_links": [link_meta],
                        "script_evidence": segment.get("evidence") or "",
                        "link_prev": False,
                        "experimental": True,
                        "preview_timeline_draft": True,
                    }
                    created = await conn.fetchrow(
                        "INSERT INTO content_nodes "
                        "(project_id,parent_id,kind,seq,title,summary,meta,status) "
                        "VALUES($1,$2,'shot',$3,$4,$5,$6::jsonb,'storyboarded') "
                        "RETURNING id,seq,title,summary,meta,status",
                        project_id, node_id, max_seq + (index + 1) * SEQ_STEP,
                        f"镜头{shot_no}", str(segment.get("picture") or ""),
                        json.dumps(shot_meta, ensure_ascii=False))
                    shot_id = int(created["id"])
                    shot_rows.append({**dict(created), "meta": shot_meta})
                    for element_id in element_ids:
                        await conn.execute(
                            "INSERT INTO element_appearances(project_id,element_id,node_id,snapshot) "
                            "VALUES($1,$2,$3,$4) ON CONFLICT(element_id,node_id) DO NOTHING",
                            project_id, element_id, shot_id,
                            str(segment.get("picture") or ""))
                segment["converted_shot_id"] = shot_id

            converted_meta = {
                **timeline,
                "segments": segments,
                "version": int(timeline.get("version") or 1) + 1,
                "status": "converted",
                "parent_timeline_attachment_id": latest["id"],
                "converted_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "preserved": True,
            }
            timeline_row = await conn.fetchrow(
                "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
                "VALUES($1,$2,'data',NULL,$3::jsonb) RETURNING id,meta,created_at",
                project_id, node_id, json.dumps(converted_meta, ensure_ascii=False))
            await conn.execute(
                "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                attachment_id, json.dumps({
                    "preview_timeline_attachment_id": timeline_row["id"],
                    "preview_timeline_version": converted_meta["version"],
                    "preview_timeline_status": "converted",
                }, ensure_ascii=False))
    return {
        "shots": shot_rows,
        "timeline": _timeline_result(timeline_row),
        "idempotent": False,
        "preserved": True,
    }


@router.post("/chapters/{node_id}/episode-flash/{attachment_id}/split-preset")
async def split_episode_flash_by_preset(project_id: int, node_id: int, attachment_id: int):
    """按母带草稿中已经落库的时间表拆分，不做镜号板视觉识别。

    第 2 镜起的计划切点恰好是单帧镜号板；拆分时排除该边界帧，其余剧情帧全部
    编进对应镜头短视频，并抽每段第一张剧情帧作为首帧。原始母带、标记母带、
    拆分运行记录与每镜短视频都永久保留。本接口不覆盖或作废已有正式分镜。
    """
    from .. import oss
    from ..services import video_preset_split
    from ..services.shot_ordering import SEQ_STEP

    pool = get_pool()
    chapter = await pool.fetchrow(
        "SELECT id,meta FROM content_nodes "
        "WHERE id=$1 AND project_id=$2 AND kind='chapter' AND deleted_at IS NULL",
        node_id, project_id)
    master = await pool.fetchrow(
        "SELECT id,url,meta FROM content_attachments "
        "WHERE id=$1 AND project_id=$2 AND node_id=$3 AND kind='video' "
        "AND meta->>'type'='episode_flash_master'",
        attachment_id, project_id, node_id)
    if not chapter or not master:
        raise HTTPException(404, "章节或镜号板母带不存在")
    master_meta = _jsonb(master["meta"])
    if master_meta.get("mode") != "slate_marked":
        raise HTTPException(409, "当前附件不是单帧镜号板实验母带")
    beats = list(master_meta.get("beats") or [])
    if not beats:
        raise HTTPException(409, "母带缺少已落库的预设时间表")
    batch_id = str(master_meta.get("batch_id") or master["id"])

    # 相同批次重复点击时只返回已创建结果，绝不重复建镜；其它正式分镜存在时拒绝，
    # 避免以“实验拆分”为名覆盖用户已经编辑过的数据。
    existing = await pool.fetch(
        "SELECT id,seq,title,summary,meta,status FROM content_nodes "
        "WHERE project_id=$1 AND parent_id=$2 AND kind='shot' AND deleted_at IS NULL "
        "AND meta->>'episode_flash_batch'=$3 "
        "AND meta->>'episode_flash_split_method'='preset_timeline' ORDER BY seq,id",
        project_id, node_id, batch_id)
    if existing:
        run = next(reversed(master_meta.get("split_runs") or []), {})
        return {
            "shots": [{**dict(row), "meta": _jsonb(row["meta"])} for row in existing],
            "split": run, "idempotent": True, "preserved": True,
        }
    other_count = await pool.fetchval(
        "SELECT count(*) FROM content_nodes WHERE project_id=$1 AND parent_id=$2 "
        "AND kind='shot' AND deleted_at IS NULL", project_id, node_id)
    if other_count:
        raise HTTPException(409, "本章已有正式分镜；为保护现有数据，预设时间表实验不会覆盖或重拆")

    run_id = uuid4().hex[:12]
    run_started = datetime.now(timezone.utc).isoformat()
    run_meta = {
        "type": "episode_flash_split_run", "run_id": run_id,
        "batch_id": batch_id, "master_attachment_id": master["id"],
        "source_video_url": master["url"], "method": "preset_timeline",
        "visual_slate_detection": False, "status": "processing",
        "created_at": run_started, "preserved": True,
    }
    manifest = await pool.fetchrow(
        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
        "VALUES($1,$2,'data',NULL,$3::jsonb) RETURNING id",
        project_id, node_id, json.dumps(run_meta, ensure_ascii=False))
    manifest_id = int(manifest["id"])

    try:
        spec = _jsonb(master_meta.get("spec"))
        split = await video_preset_split.split_by_preset_timeline(
            str(master["url"]), beats,
            fps=int(spec.get("fps") or 24),
            frame_count=int(spec["frame_count"]) if spec.get("frame_count") else None,
        )

        semaphore = asyncio.Semaphore(6)

        async def store_segment(segment: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                video_url, keyframe_url = await asyncio.gather(
                    oss.store_bytes(
                        segment["video_bytes"],
                        prefix=f"episode_flash_split/{project_id}/{run_id}", ext=".mp4"),
                    oss.store_bytes(
                        segment["keyframe_bytes"],
                        prefix=f"episode_flash_split/{project_id}/{run_id}", ext=".jpeg"),
                )
            if not video_url or not keyframe_url:
                raise RuntimeError(f"镜{segment['shot_no']}的短视频或首帧未能永久存储")
            return {
                **{key: value for key, value in segment.items()
                   if key not in ("video_bytes", "keyframe_bytes")},
                "video_url": video_url, "keyframe_url": keyframe_url,
            }

        outputs = await asyncio.gather(*(store_segment(segment) for segment in split["segments"]))
        # 上传完成即先挂回运行清单；即便后续数据库事务失败，已产生的测试文件仍可追踪。
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({
                "status": "stored", "outputs": outputs,
                "source_frame_count": split["source_frame_count"],
                "total_content_frames": split["total_content_frames"],
                "boundary_frames": split["boundary_frames"],
                "slate_frames": split["boundary_frames"][1:],
            }, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({
                "status": "failed", "error": str(exc)[:500],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        raise HTTPException(502, f"预设时间表拆分失败；运行记录{manifest_id}已保留：{str(exc)[:260]}")

    refs = list(master_meta.get("refs") or [])
    shot_rows: list[dict[str, Any]] = []
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 媒体处理期间再次检查，防止另一请求或人工拆镜抢先落库。
                await conn.fetchval(
                    "SELECT id FROM content_nodes WHERE id=$1 FOR UPDATE", node_id)
                conflict_rows = await conn.fetch(
                    "SELECT id FROM content_nodes WHERE project_id=$1 AND parent_id=$2 "
                    "AND kind='shot' AND deleted_at IS NULL FOR UPDATE",
                    project_id, node_id)
                if conflict_rows:
                    raise RuntimeError("媒体拆分期间本章出现了正式分镜，系统已停止写入以保护现有数据")

                scene_seg = 0
                previous_scene = None
                for index, (beat, segment) in enumerate(zip(beats, outputs, strict=True), 1):
                    scene = str(beat.get("scene") or "")
                    if index == 1 or scene != previous_scene:
                        scene_seg += 1
                        previous_scene = scene
                    characters = [str(name) for name in (beat.get("characters") or []) if name]
                    selected_refs = [ref for ref in refs if (
                        ref.get("kind") == "scene" or ref.get("name") in characters)]
                    element_ids = [int(ref["element_id"]) for ref in selected_refs
                                   if ref.get("element_id") is not None]
                    shot_no = int(beat.get("no") or index)
                    actual_duration = round(float(segment["frame_count"]) / float(split["fps"]), 3)
                    shot_meta = {
                        "shot_no": shot_no, "scene": scene, "scene_element": scene,
                        "scene_seg": scene_seg, "scale": beat.get("shot_size") or "中景",
                        "duration_s": actual_duration, "action": beat.get("picture") or "",
                        "dialogue": "无", "characters": characters, "element_ids": element_ids,
                        "reference_images": [
                            {key: ref.get(key) for key in ("name", "kind", "url")}
                            for ref in selected_refs],
                        "reference_urls": [ref.get("url") for ref in selected_refs if ref.get("url")],
                        "keyframe_url": segment["keyframe_url"],
                        "video_cover_url": segment["keyframe_url"],
                        "video_url": segment["video_url"],
                        "keyframe_source": "episode_flash_extract",
                        "experimental": True, "episode_flash_batch": batch_id,
                        "episode_flash_at": float(beat.get("output_start_s") or 0),
                        "episode_flash_end": float(beat.get("output_end_s") or 0),
                        "episode_flash_split_method": "preset_timeline",
                        "episode_flash_visual_detection": False,
                        "episode_flash_run_id": run_id,
                        "episode_flash_manifest_id": manifest_id,
                        "episode_flash_master_attachment_id": master["id"],
                        "episode_flash_source_start_frame": segment["start_frame"],
                        "episode_flash_source_end_frame": segment["end_frame"],
                        "episode_flash_content_frame_count": segment["frame_count"],
                        "episode_flash_all_frames_in_video": True,
                        "link_prev": False,
                    }
                    row = await conn.fetchrow(
                        "INSERT INTO content_nodes "
                        "(project_id,parent_id,kind,seq,title,summary,meta,status) "
                        "VALUES($1,$2,'shot',$3,$4,$5,$6::jsonb,'rendered') "
                        "RETURNING id,seq,title,summary,meta,status",
                        project_id, node_id, index * SEQ_STEP, f"镜头{shot_no}",
                        str(beat.get("picture") or ""),
                        json.dumps(shot_meta, ensure_ascii=False))
                    shot_id = int(row["id"])
                    keyframe_attachment_id = await conn.fetchval(
                        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
                        "VALUES($1,$2,'image',$3,$4::jsonb) RETURNING id",
                        project_id, shot_id, segment["keyframe_url"], json.dumps({
                            "type": "episode_flash_keyframe", "run_id": run_id,
                            "batch_id": batch_id, "shot_no": shot_no,
                            "source_attachment_id": master["id"],
                            "source_frame": segment["start_frame"],
                            "split_method": "preset_timeline", "preserved": True,
                        }, ensure_ascii=False))
                    video_attachment_id = await conn.fetchval(
                        "INSERT INTO content_attachments(project_id,node_id,kind,url,meta) "
                        "VALUES($1,$2,'video',$3,$4::jsonb) RETURNING id",
                        project_id, shot_id, segment["video_url"], json.dumps({
                            "type": "episode_flash_shot_video", "run_id": run_id,
                            "batch_id": batch_id, "shot_no": shot_no,
                            "source_attachment_id": master["id"],
                            "start_frame": segment["start_frame"],
                            "end_frame": segment["end_frame"],
                            "frame_count": segment["frame_count"], "fps": split["fps"],
                            "split_method": "preset_timeline",
                            "all_content_frames_preserved": True, "preserved": True,
                        }, ensure_ascii=False))
                    shot_meta["episode_flash_keyframe_attachment_id"] = keyframe_attachment_id
                    shot_meta["episode_flash_video_attachment_id"] = video_attachment_id
                    await conn.execute(
                        "UPDATE content_nodes SET meta=$2::jsonb WHERE id=$1",
                        shot_id, json.dumps(shot_meta, ensure_ascii=False))
                    for element_id in element_ids:
                        await conn.execute(
                            "INSERT INTO element_appearances(project_id,element_id,node_id,snapshot) "
                            "VALUES($1,$2,$3,$4) ON CONFLICT(element_id,node_id) DO NOTHING",
                            project_id, element_id, shot_id, str(beat.get("picture") or ""))
                    shot_rows.append({**dict(row), "meta": shot_meta})

                split_summary = {
                    "run_id": run_id, "manifest_attachment_id": manifest_id,
                    "method": "preset_timeline", "visual_slate_detection": False,
                    "master_attachment_id": master["id"], "shot_count": len(shot_rows),
                    "boundary_frames": split["boundary_frames"],
                    "slate_frames": split["boundary_frames"][1:],
                    "source_frame_count": split["source_frame_count"],
                    "total_content_frames": split["total_content_frames"],
                    "excluded_slate_frames": max(0, len(split["boundary_frames"]) - 1),
                    "status": "done", "created_at": run_started,
                    "finished_at": datetime.now(timezone.utc).isoformat(), "preserved": True,
                }
                locked_master_meta = _jsonb(await conn.fetchval(
                    "SELECT meta FROM content_attachments WHERE id=$1 FOR UPDATE", master["id"]))
                split_runs = list(locked_master_meta.get("split_runs") or [])
                split_runs.append(split_summary)
                locked_master_meta.update({
                    "split_runs": split_runs, "split_method": "preset_timeline",
                    "visual_slate_detection": False, "status": "sampled",
                    "frames": len(shot_rows),
                    "total_extracted_frames": split["total_content_frames"],
                })
                await conn.execute(
                    "UPDATE content_attachments SET meta=$2::jsonb WHERE id=$1",
                    master["id"], json.dumps(locked_master_meta, ensure_ascii=False))
                await conn.execute(
                    "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
                    manifest_id, json.dumps({
                        **split_summary, "shot_ids": [row["id"] for row in shot_rows],
                        "status": "done",
                    }, ensure_ascii=False))

                chapter_meta = _jsonb(await conn.fetchval(
                    "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", node_id))
                for saved_batch in chapter_meta.get("episode_flash_batches") or []:
                    if str(saved_batch.get("id")) == batch_id:
                        saved_batch.update({
                            "status": "sampled", "frames": len(shot_rows),
                            "visible_frames": len(shot_rows), "split_runs": split_runs,
                            "split_method": "preset_timeline",
                            "total_extracted_frames": split["total_content_frames"],
                        })
                latest = chapter_meta.get("episode_flash") or {}
                if str(latest.get("id")) == batch_id:
                    latest.update({
                        "status": "sampled", "frames": len(shot_rows),
                        "visible_frames": len(shot_rows), "split_runs": split_runs,
                        "split_method": "preset_timeline",
                        "total_extracted_frames": split["total_content_frames"],
                    })
                await conn.execute(
                    "UPDATE content_nodes SET meta=$2::jsonb,updated_at=now() WHERE id=$1",
                    node_id, json.dumps(chapter_meta, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        await pool.execute(
            "UPDATE content_attachments SET meta=meta || $2::jsonb WHERE id=$1",
            manifest_id, json.dumps({
                "status": "failed_after_store", "error": str(exc)[:500],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        raise HTTPException(
            502, f"短视频均已保留在拆分清单{manifest_id}，但正式分镜落库失败：{str(exc)[:240]}")

    return {"shots": shot_rows, "split": split_summary,
            "idempotent": False, "preserved": True}


@router.get("/chapters/{node_id}/shots")
async def list_shots(project_id: int, node_id: int):
    """本章分镜清单。取数走 workflow_actions.chapter_shots（全站唯一实现，
    工作流的循环数据源与本端点同源），这里只把它裁回端点的历史返回形状。"""
    from ..services.workflow_actions import chapter_shots

    out = await chapter_shots(get_pool(), project_id=project_id, chapter_id=node_id)
    return [{"id": i["shot_id"], "seq": i["seq"], "title": i["title"],
             "summary": i["summary"], "meta": i["meta"], "status": i["status"]}
            for i in out["items"]]


class InsertShotIn(BaseModel):
    after_shot_id: int | None = None  # 在此镜之后插入；None=插到本章最前（空章=第一镜）


@router.post("/chapters/{node_id}/shots/insert")
async def insert_shot(project_id: int, node_id: int, body: InsertShotIn):
    """在两镜之间插入一个空白镜（时间轴悬停「+」触发）：
    排序键 seq 取前后两镜中点（无整数间隙时先把全章兄弟按 SEQ_STEP 惰性重排，相对顺序与各自
    shot_no 均不变）；展示镜号 shot_no 生成一个介于前后镜之间的可读十进制号（8/9→8.5，8.1/8.2→8.15）。
    新镜只含骨架 meta（时长默认5s、空脚本），待用户填脚本后再生成提示词/首帧/视频；
    已有各镜的提示词/角色/产物均绑定其行 id，插入互不影响。"""
    from ..services.shot_ordering import SEQ_STEP, between_labels

    pool = get_pool()
    if not await pool.fetchval(
        "SELECT 1 FROM content_nodes WHERE id=$1 AND kind='chapter' AND project_id=$2",
        node_id, project_id):
        raise HTTPException(404, "章节不存在")
    async with pool.acquire() as conn:
        async with conn.transaction():
            sibs = await conn.fetch(
                "SELECT id, seq, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
                "AND deleted_at IS NULL ORDER BY seq, id FOR UPDATE", node_id)
            idx = -1  # after 镜在 sibs 中的下标；-1=插到最前
            if body.after_shot_id is not None:
                idx = next((i for i, s in enumerate(sibs) if s["id"] == body.after_shot_id), None)
                if idx is None:
                    raise HTTPException(404, "指定的前一镜不存在或不属于本章")
            prev = sibs[idx] if idx >= 0 else None
            nxt = sibs[idx + 1] if idx + 1 < len(sibs) else None
            prev_seq = prev["seq"] if prev else 0
            nxt_seq = nxt["seq"] if nxt else prev_seq + 2 * SEQ_STEP
            if nxt_seq - prev_seq < 2:  # 无整数空隙：全章兄弟按 SEQ_STEP 惰性重排（不动 shot_no）
                for i, s in enumerate(sibs):
                    await conn.execute(
                        "UPDATE content_nodes SET seq=$2 WHERE id=$1", s["id"], (i + 1) * SEQ_STEP)
                prev_seq = (idx + 1) * SEQ_STEP if idx >= 0 else 0
                nxt_seq = (idx + 2) * SEQ_STEP if idx + 1 < len(sibs) else prev_seq + 2 * SEQ_STEP
            new_seq = (prev_seq + nxt_seq) // 2
            label = between_labels(
                _jsonb(prev["meta"]).get("shot_no") if prev else None,
                _jsonb(nxt["meta"]).get("shot_no") if nxt else None)
            meta = {"shot_no": label, "scene": "", "scene_element": "", "scale": "中景",
                    "duration_s": 5, "action": "", "dialogue": "无", "characters": [],
                    "element_ids": [], "link_prev": False, "manual_insert": True}
            row = await conn.fetchrow(
                "INSERT INTO content_nodes (project_id, parent_id, kind, seq, title, summary, meta, status) "
                "VALUES ($1,$2,'shot',$3,$4,'',$5::jsonb,'storyboarded') "
                "RETURNING id, seq, title, summary, meta, status",
                project_id, node_id, new_seq, f"镜头{label}",
                json.dumps(meta, ensure_ascii=False))
    return {**dict(row), "meta": _jsonb(row["meta"])}


@router.delete("/shots/{shot_id}")
async def delete_shot(project_id: int, shot_id: int):
    """删除单个分镜→移入回收站（软删除 deleted_at）：镜行保留，视频/首帧附件不级联清理，
    资料完整留存（回收站可查看/彻底删除，暂不恢复）。同步清掉该镜的要素出现索引（派生索引，
    不该让回收镜污染要素召回）。不重排其它镜 seq、不回收 shot_no——镜号自然「永久保留、不复用」。"""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            r = await conn.execute(
                "UPDATE content_nodes SET deleted_at=now(), updated_at=now() "
                "WHERE id=$1 AND kind='shot' AND project_id=$2 AND deleted_at IS NULL",
                shot_id, project_id)
            if r.rsplit(" ", 1)[-1] == "0":
                raise HTTPException(404, "分镜不存在或已在回收站")
            await conn.execute("DELETE FROM element_appearances WHERE node_id=$1", shot_id)
    return {"ok": True}


# ═══════════════ 场景组（空间锚定，2026-07-16） ═══════════════

@router.get("/chapters/{node_id}/scene-groups")
async def list_scene_groups(project_id: int, node_id: int):
    """读本章场景组（空间规划产物）：分组/空间布局/角色占位/场景空间站位图提示词与成图。
    前端分镜板按组分节展示 + 场景图人工确认生成入口。"""
    from ..services import scene_blocking

    # 先按附件表补回缺失的 sheet_url（历史丢更新自愈，幂等且无图时零开销）
    await scene_blocking.backfill_sheet_urls(get_pool(), node_id)
    row = await get_pool().fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter'", node_id)
    if not row:
        raise HTTPException(404, "章节不存在")
    meta = _jsonb(row["meta"])
    sb = meta.get("scene_blocking") or {}
    return {"groups": sb.get("groups") or [], "at": sb.get("at"),
            "gen": (meta.get("gen") or {}).get("scene_blocking")}


@router.get("/chapters/{node_id}/continuity")
async def chapter_continuity(project_id: int, node_id: int):
    """读取本章最新连续性契约、Beat、镜头前后状态与校验结果。"""
    scenes = await get_pool().fetch(
        "SELECT ns.id,ns.scene_code,ns.title,ns.seq,ns.source_meta,"
        "c.id AS contract_id,c.version,c.hard_locks,c.initial_state,c.status "
        "FROM narrative_scenes ns "
        "JOIN LATERAL (SELECT * FROM scene_continuity_contracts "
        " WHERE narrative_scene_id=ns.id ORDER BY version DESC LIMIT 1) c ON true "
        "WHERE ns.project_id=$1 AND ns.chapter_id=$2 ORDER BY ns.seq",
        project_id, node_id)
    shots = await get_pool().fetch(
        "SELECT n.id AS shot_id,n.seq,n.meta->>'shot_no' AS shot_no,"
        "s.id AS state_id,s.version,s.scene_contract_id,s.beat_ids,s.script_evidence,"
        "s.before_state,s.action_transition,s.after_state,s.status "
        "FROM content_nodes n "
        "JOIN LATERAL (SELECT * FROM shot_continuity_states "
        " WHERE shot_id=n.id ORDER BY version DESC LIMIT 1) s ON true "
        "WHERE n.project_id=$1 AND n.parent_id=$2 AND n.kind='shot' "
        "AND n.deleted_at IS NULL ORDER BY n.seq,n.id",
        project_id, node_id)
    checks = await get_pool().fetch(
        "SELECT id,shot_state_id,check_type,passed,errors,checked_at "
        "FROM continuity_checks WHERE project_id=$1 AND chapter_id=$2 "
        "ORDER BY id DESC LIMIT 200", project_id, node_id)
    return {
        "scenes": [{**dict(r), "source_meta": _jsonb(r["source_meta"]),
                    "hard_locks": _jsonb(r["hard_locks"]),
                    "initial_state": _jsonb(r["initial_state"])} for r in scenes],
        "shots": [{**dict(r), "beat_ids": list(r["beat_ids"] or []),
                   "script_evidence": _jsonb(r["script_evidence"]),
                   "before_state": _jsonb(r["before_state"]),
                   "action_transition": _jsonb(r["action_transition"]),
                   "after_state": _jsonb(r["after_state"])} for r in shots],
        "checks": [{**dict(r), "errors": _jsonb(r["errors"])} for r in checks],
    }


@router.post("/chapters/{node_id}/scene-blocking")
async def run_scene_blocking(
    project_id: int, node_id: int, force: bool = False, seg: int | None = None,
):
    """手动（重）跑场景空间规划（异步任务）：场景归组 + 逐组站位链 + 单幅场景参考图提示词。
    默认指纹缓存命中的组跳过；force=true 全量重规划（不作废已生成的参考图）。"""
    n = await get_pool().fetchval(
        "SELECT count(*) FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL",
        node_id)
    if not n:
        raise HTTPException(400, "请先拆分镜")
    return await flow.enqueue(
        get_pool(), kind="scene_blocking", project_id=project_id, node_id=node_id,
        payload={"force": force, **({"only_seg": seg} if seg is not None else {})}, priority=10)


class SceneSheetPromptIn(BaseModel):
    sheet_prompt: str
    stage: str = "sheet"  # sheet=角色站位图 / empty=空场景基准图


@router.patch("/chapters/{node_id}/scene-groups/{seg}")
async def save_scene_sheet_prompt(project_id: int, node_id: int, seg: int, body: SceneSheetPromptIn):
    """保存人工编辑后的场景图提示词（确认环节）：按 stage 写回组条目的对应阶段。
    双字段：编辑框含分隔线 → 拆 用户段/锚定段 分别落库并按变动打冻结标记（重规划只刷新
    未冻结段）；无分隔线 → 整段落 <stage>_prompt（旧语义）。"""
    from ..services import prompt_fields as pf

    if not body.sheet_prompt.strip():
        raise HTTPException(400, "提示词不能为空")
    stage = body.stage if body.stage in ("sheet", "empty") else "sheet"
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter' FOR UPDATE", node_id)
            if not row:
                raise HTTPException(404, "章节不存在")
            sb = _jsonb(row["meta"]).get("scene_blocking") or {}
            grp = next((g for g in sb.get("groups") or []
                        if int(g.get("seg") or 0) == seg), None)
            if not grp:
                raise HTTPException(404, f"场景组 {seg} 不存在——请先运行场景空间规划")
            _seg2 = pf.split_edit_text(body.sheet_prompt)
            if _seg2:
                user, anchor = _seg2
                if user != (grp.get(f"{stage}_prompt_user") or ""):
                    grp[f"{stage}_prompt_user_edited"] = True
                if anchor != (grp.get(f"{stage}_prompt_anchor") or ""):
                    grp[f"{stage}_prompt_anchor_edited"] = True
                grp[f"{stage}_prompt_user"], grp[f"{stage}_prompt_anchor"] = user, anchor
                grp[f"{stage}_prompt"] = pf.compose(user, anchor)
            else:
                grp[f"{stage}_prompt"] = body.sheet_prompt.strip()
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                node_id, json.dumps({"scene_blocking": sb}, ensure_ascii=False))
    return {"ok": True, "seg": seg, "stage": stage}


class SceneSheetIn(BaseModel):
    prompt: str | None = None  # 弹框编辑后的提示词覆盖（缺省用组条目对应阶段的提示词）


@router.post("/chapters/{node_id}/scene-groups/{seg}/empty")
async def gen_scene_empty(project_id: int, node_id: int, seg: int, body: SceneSheetIn | None = None):
    """第一阶段：生成本场景组的**空场景基准图**（无人）。它是站位图与组内各镜的空间真值。

    走 enqueue_with_deps——组条目还没有 empty_prompt（旧单阶段数据/从未规划）时自动先派
    scene_blocking 把提示词生产出来。此前这里用的是普通 enqueue，missing_deps 压根不会被
    调用，任务直接判 Blocked「提示词为空，请先运行场景空间规划」，用户只能看着它反复失败。"""
    from ..services import prompt_fields as pf

    prompt = pf.strip_dividers(body.prompt) if body and body.prompt else None
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_scene_empty", project_id=project_id, node_id=node_id,
        payload={"seg": seg, **({"prompt": prompt} if prompt else {})},
        priority=10)


@router.post("/chapters/{node_id}/scene-groups/{seg}/sheet")
async def gen_scene_sheet(project_id: int, node_id: int, seg: int, body: SceneSheetIn | None = None):
    """第二阶段：在空场景基准图上生成**角色站位图**（人工确认后点击，异步任务）。
    走 enqueue_with_deps——本组还没有基准图时自动先派 gen_scene_empty，
    两阶段不能跳（跳了就退回"纯文字塑造空间"的老毛病）。
    弹框直传的提示词可能含双字段分隔线——剥掉再入队。"""
    from ..services import prompt_fields as pf

    prompt = pf.strip_dividers(body.prompt) if body and body.prompt else None
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_scene_sheet", project_id=project_id, node_id=node_id,
        payload={"seg": seg, **({"prompt": prompt} if prompt else {})},
        priority=10)


@router.post("/chapters/{node_id}/stills")
async def gen_stills(project_id: int, node_id: int):
    """整集分镜定格选取：一次 LLM 通读本集全部镜头，为每镜选定唯一的分镜定格
    （role=首帧/关键帧/尾帧 + 可定格的瞬间描述），落 meta.storyboard_still。
    装配期据此覆盖"机械取首切"的老口径，定格提示词随后走既有九维质检。"""
    return await flow.enqueue(
        get_pool(), kind="gen_stills", project_id=project_id, node_id=node_id,
        payload={}, priority=9)


class SceneSheetsGroupIn(BaseModel):
    segs: list[int] = []        # 指定场景（缺省=本集所有缺图的场景）
    force: bool = False         # 已有图的场景也重出
    note: str | None = None     # 组图全局要求（画布内可编辑）


@router.post("/chapters/{node_id}/scene-groups/sheets")
async def gen_scene_sheets_group(project_id: int, node_id: int,
                                 body: SceneSheetsGroupIn | None = None):
    """整集场景图组图：本集全部场景的空间与站位参考图一次出齐（Seedream 组图）。
    跨场景一致性靠它——N 张共享同一生成上下文，画风与色彩基调天然统一；
    各场景的时间/天气/光线仍由各自的连续性硬锁分别钉住，不会互相污染。"""
    body = body or SceneSheetsGroupIn()
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_scene_sheets_group", project_id=project_id, node_id=node_id,
        payload={"segs": body.segs, "force": body.force, "note": (body.note or "").strip()},
        priority=8)


class StoryboardGridIn(BaseModel):
    board: int | None = None    # 只重出第 N 张（画布内单张重出）；缺省=整章重出
    prompt: str | None = None   # 画布里确认/改写过的该张提示词正文（模板前言仍由 run 拼）


@router.post("/chapters/{node_id}/storyboard-grid")
async def gen_storyboard_grid(project_id: int, node_id: int, body: StoryboardGridIn | None = None):
    """章级分镜总览宫格故事板（一集多张 3:2，每张 ≤16 格）：约束镜头间连贯，
    「按本张出图」批量首帧时整张作构图参考（固定格位引用句）。仅手动触发（2026-07-12 起
    拆镜后不再自动串出，也不再串 gen_prompts）；前置仍幂等补详细分镜兜底。
    分镜图画布提交 board(+prompt) → 只重出该张、用画布里的提示词。"""
    n = await get_pool().fetchval(
        "SELECT count(*) FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL",
        node_id,
    )
    if not n:
        raise HTTPException(400, "请先拆分镜")
    from ..services import prompt_fields as pf

    payload: dict[str, Any] = {}
    if body and body.board is not None:
        payload["board"] = body.board
        if body.prompt and body.prompt.strip():
            payload["prompt"] = pf.strip_dividers(body.prompt)
    return await flow.enqueue(
        get_pool(), kind="gen_overview_grid", project_id=project_id, node_id=node_id,
        payload=payload, priority=10,
    )


@router.get("/chapters/{node_id}/storyboard-grid/canvas")
async def storyboard_grid_canvas(project_id: int, node_id: int, shot_id: int | None = None):
    """分镜图（章级宫格故事板）画布的运行实例：按当前分板重新装配逐张提示词与参考设定图，
    与已出图的总览条目合并——画布内可确认/改写提示词后单张重出。
    shot_id 给定时回一个 focus_board（该镜所在的那张），画布默认聚焦它。"""
    from ..services.overview_grid import assemble_overview_boards

    pool = get_pool()
    chapter = await pool.fetchrow(
        "SELECT id, seq, title, meta FROM content_nodes WHERE id=$1 AND kind='chapter'", node_id)
    if not chapter:
        raise HTTPException(404, "章节不存在")
    try:
        boards = await assemble_overview_boards(pool, project_id, node_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    meta = _jsonb(chapter["meta"])
    done = {b.get("no"): b for b in ((meta.get("storyboard_overview") or {}).get("boards") or [])}
    focus = None
    if shot_id is not None:
        shot = await pool.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
        if shot:
            focus = (_jsonb(shot["meta"]).get("storyboard_ref") or {}).get("board")
            if focus is None:  # 还没出过图 → 按分板结果反查本镜落在第几张
                focus = next((b["no"] for b in boards if shot_id in b["shot_ids"]), None)
    return {
        "chapter": {"id": node_id, "seq": chapter["seq"], "title": chapter["title"]},
        "focus_board": focus or (boards[0]["no"] if boards else None),
        "gen": (meta.get("gen") or {}).get("overview_grid"),
        "boards": [{
            "no": b["no"], "rows": b["rows"], "cols": b["cols"],
            "shot_ids": b["shot_ids"], "shot_nos": b["shot_nos"], "scenes": b["scenes"],
            "prompt": b["prompt"], "element_refs": b["element_refs"],
            "url": (done.get(b["no"]) or {}).get("url"),
        } for b in boards],
    }


@router.get("/chapters/{node_id}/storyboard-overview")
async def get_storyboard_overview(project_id: int, node_id: int):
    """读章级总览草图（页列表含镜号/场景标注 + 生成状态）：前端头部按钮与轮询用。"""
    row = await get_pool().fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter'", node_id
    )
    if not row:
        raise HTTPException(404, "章节不存在")
    meta = _jsonb(row["meta"])
    return {"overview": meta.get("storyboard_overview"),
            "gen": (meta.get("gen") or {}).get("overview_grid")}


@router.post("/chapters/{node_id}/storyboard-grid/{board}/keyframes")
async def batch_keyframes_by_board(project_id: int, node_id: int, board: int, force: bool = False):
    """按某张宫格故事板批量生成其覆盖各镜的彩色首帧（每镜以整张故事板作构图参考+固定格位引用句——
    use_storyboard 显式挂载，普通首帧生成不再自动挂故事板）。
    默认跳过已有首帧的镜；force=true 全部重出。张→镜的对应关系取自 shot.meta.storyboard_ref.board。"""
    rows = await get_pool().fetch(
        "SELECT id, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL "
        "ORDER BY seq", node_id
    )
    tasks = []
    for r in rows:
        meta = _jsonb(r["meta"])
        if (meta.get("storyboard_ref") or {}).get("board") != board:
            continue
        if meta.get("keyframe_url") and not force:
            continue
        # 依赖 DAG：缺提示词的镜自动带出 gen_prompts 子任务，不再静默跳过
        q = await flow.enqueue_with_deps(
            get_pool(), kind="gen_keyframe", project_id=project_id, node_id=r["id"],
            payload={"prompt": meta.get("image_prompt"), "use_storyboard": True,
                     "prompt_overridden": bool(meta.get("image_prompt_edited")),
                     "reference_images": meta.get("reference_images") or []},
            priority=0,
        )
        tasks.append({"shot_id": r["id"], "task_id": q["task_id"]})
    if not tasks and not any(
        (_jsonb(r["meta"]).get("storyboard_ref") or {}).get("board") == board for r in rows
    ):
        raise HTTPException(400, f"宫格故事板第{board}张不存在或未关联任何分镜（请先生成总览宫格）")
    return {"queued": len(tasks), "tasks": tasks}


class PromptsIn(BaseModel):
    only: str | None = None  # image=只重生成首帧提示词 / video=只视频 / None=两者
    redesign_cuts: bool = False


def _canvas_state(meta: dict[str, Any], slot: str, present: bool,
                  failed: bool = False) -> tuple[str, str | None]:
    state = (meta.get("gen") or {}).get(slot) or {}
    raw = state.get("state")
    if raw in {"waiting_deps", "pending", "running"}:
        return raw, state.get("error")
    if raw in {"failed", "canceled"}:
        return raw, state.get("error")
    if failed:
        return "failed", None
    return ("done" if present else "empty"), None


@router.get("/shots/{shot_id}/production-canvas")
async def shot_production_canvas(project_id: int, shot_id: int):
    """单镜头生产 SOP 的运行实例：固定节点来自真实业务字段，状态来自 meta.gen 与质检结果。"""
    pool = get_pool()
    shot = await pool.fetchrow(
        "SELECT id,parent_id,title,summary,meta,status FROM content_nodes "
        "WHERE id=$1 AND project_id=$2 AND kind='shot' AND deleted_at IS NULL",
        shot_id, project_id)
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    body = await pool.fetchval(
        "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
        shot["parent_id"])
    from ..services import references as reference_service
    refs = await reference_service.list_resolved(
        pool, project_id=project_id, subject_kind="shot", subject_id=shot_id, purpose="image")
    cuts = list(meta.get("cuts") or [])
    image_review = meta.get("prompt_review_image") or {}
    video_review = meta.get("prompt_review") or {}
    prompt_state, prompt_error = _canvas_state(
        meta, "prompts", bool(meta.get("image_prompt") or meta.get("video_prompt")))
    keyframe_state, keyframe_error = _canvas_state(meta, "keyframe", bool(meta.get("keyframe_url")))
    video_state, video_error = _canvas_state(meta, "video", bool(meta.get("video_url")))

    def node(node_id: str, label: str, kind: str, status: str, **extra: Any) -> dict[str, Any]:
        return {"id": node_id, "label": label, "kind": kind, "status": status,
                "fixed": True, **extra}

    nodes = [
        node("source_script", "原始剧本", "text", "done" if body else "empty",
             content=(body or "")[:4000], rerunnable=False),
        node("rough_storyboard", "分镜粗剧本", "text", "done",
             content="｜".join(str(x) for x in (
                 meta.get("scene"), meta.get("scale"), meta.get("duration_s")) if x),
             rerunnable=False),
        node("shot_detail", "详细分镜", "text",
             "empty" if meta.get("detail_pending") else "done",
             content=shot["summary"] or "", rerunnable=False),
        node("cuts", "生成分镜剧本", "text",
             "done" if cuts or meta.get("storyboard_script_ready") else "empty",
             content="\n".join(
                 f"{sum(max(1, int(x.get('seconds') or 2)) for x in cuts[:i])}-"
                 f"{sum(max(1, int(x.get('seconds') or 2)) for x in cuts[:i + 1])}秒 · "
                 f"{'硬切 CUT · ' if i else '起镜 · '}{c.get('scale', '')} · "
                 f"{c.get('subject', '')} · {c.get('action', '')}" for i, c in enumerate(cuts)),
             rerunnable=True,
             detail="连续单镜，无需硬切" if meta.get("storyboard_script_ready") and not cuts else None),
        node("continuity", "场景站位与连续性", "text",
             "done" if meta.get("blocking") else "empty",
             content=json.dumps(meta.get("blocking") or {}, ensure_ascii=False), rerunnable=False),
        node("references", "参考素材池", "image", "done" if refs else "empty",
             refs=refs, url=next((r.get("url") for r in refs if r.get("url")), None),
             rerunnable=False),
        node("image_prompt", "首帧提示词", "text", prompt_state if meta.get("image_prompt") else "empty",
             content=meta.get("image_prompt") or "", error=prompt_error, rerunnable=True),
        node("image_qc", "首帧提示词质检", "quality",
             "done" if image_review.get("合格") else ("failed" if image_review else "empty"),
             content=json.dumps(image_review, ensure_ascii=False), rerunnable=True),
        node("keyframe", "分镜首图", "image", keyframe_state,
             url=meta.get("keyframe_url"), error=keyframe_error, rerunnable=True),
        node("video_prompt", "视频提示词", "text", prompt_state if meta.get("video_prompt") else "empty",
             content=meta.get("video_prompt") or "", error=prompt_error, rerunnable=True),
        node("video_qc", "视频提示词质检", "quality",
             "done" if video_review.get("合格") else ("failed" if video_review else "empty"),
             content=json.dumps(video_review, ensure_ascii=False), rerunnable=True),
        node("audio_precheck", "音频预检", "quality",
             "done" if meta.get("audio_precheck") else "optional",
             content=json.dumps(meta.get("audio_precheck") or {}, ensure_ascii=False),
             rerunnable=True),
        node("video", "成品视频", "video", video_state,
             url=meta.get("video_url"), error=video_error, rerunnable=True),
    ]
    edges = [
        ("source_script", "rough_storyboard"), ("rough_storyboard", "shot_detail"),
        ("shot_detail", "cuts"), ("cuts", "continuity"), ("continuity", "references"),
        ("references", "image_prompt"), ("image_prompt", "image_qc"),
        ("image_qc", "keyframe"), ("references", "video_prompt"),
        ("cuts", "video_prompt"), ("video_prompt", "video_qc"),
        ("video_qc", "video"), ("keyframe", "video"), ("audio_precheck", "video"),
    ]
    return {
        "shot_id": shot_id, "title": f"镜头 {meta.get('shot_no') or shot_id}",
        "sop_code": "shot_production_sop", "sop_version": 1,
        "nodes": nodes,
        "edges": [{"source": source, "target": target, "type": "dep"}
                  for source, target in edges],
    }


class CanvasNodeRunIn(BaseModel):
    scope: Literal["self", "with_dependencies"] = "with_dependencies"


@router.post("/shots/{shot_id}/production-canvas/nodes/{canvas_node_id}/run")
async def run_shot_canvas_node(
    project_id: int, shot_id: int, canvas_node_id: str,
    body: CanvasNodeRunIn | None = None,
):
    """统一节点执行入口：self 只跑本节点；with_dependencies 自动补齐缺失前置后再跑本节点。

    payload 装配收敛在 services/production_canvas.step_payload——智能体编排 run-unit
    跑同一个 step 也走那一份，两边永远同一条链路（对齐 2026-07-30）。"""
    scope = body.scope if body else "with_dependencies"
    enqueue = flow.enqueue if scope == "self" else flow.enqueue_with_deps
    pool = get_pool()
    if canvas_node_id == "audio_precheck":
        return await audio_precheck(project_id, shot_id)
    mapped = production_canvas.NODE_STEPS.get(canvas_node_id)
    if not mapped:
        raise HTTPException(400, "该固定节点不支持单独重跑")
    kind, only = mapped
    try:
        payload = await production_canvas.step_payload(
            pool, kind, project_id, shot_id, only=only)
    except production_canvas.CanvasError as e:
        raise HTTPException(404, str(e)) from e
    return await enqueue(pool, kind=kind, project_id=project_id,
                         node_id=shot_id, payload=payload, priority=10)


@router.post("/shots/{shot_id}/prompts")
async def gen_prompts(project_id: int, shot_id: int, body: PromptsIn | None = None):
    """提示词生成（含质检）：异步任务——装配三套专业提示词 → 九维评审（only 可只审一侧）
    → 不合格自动重构 → 复审 → 结果带指纹+有效期落 meta。"""
    payload = {}
    if body and body.only in ("image", "video"):
        payload["only"] = body.only
    if body and body.redesign_cuts:
        payload["redesign_cuts"] = True
    return await flow.enqueue(
        get_pool(), kind="gen_prompts", project_id=project_id, node_id=shot_id,
        payload=payload, priority=10,
    )


class ExtraRef(BaseModel):
    name: str
    kind: str = "asset"
    url: str


class ExtraRefIn(BaseModel):
    add: ExtraRef | None = None
    remove: str | None = None  # 参考名


@router.patch("/shots/{shot_id}/extra-refs")
async def update_shot_extra_refs(project_id: int, shot_id: int, body: ExtraRefIn):
    """增删本镜手选的额外参考图（公共图片生成弹框·资产面板挑的项目资产：首帧/故事板/封面等任意图）。
    存 meta.extra_refs，生成前重装配时并入参考图池；启停沿用 /refs 的 ref_off（按名）。要素类走 /elements。"""
    if not body.add and not body.remove:
        raise HTTPException(400, "缺少 add 或 remove")
    pool = get_pool()
    shot = await pool.fetchrow("SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not shot:
        raise HTTPException(404, "分镜不存在")
    refs = list(_jsonb(shot["meta"]).get("extra_refs") or [])
    if body.add:
        refs = [r for r in refs if r.get("name") != body.add.name] + [body.add.model_dump()]
    if body.remove:
        refs = [r for r in refs if r.get("name") != body.remove]
    await pool.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps({"extra_refs": refs}, ensure_ascii=False))
    from ..services import references as reference_service
    for purpose in ("image", "video", "last"):
        await reference_service.sync_shot_from_legacy(pool, project_id, shot_id, purpose)
    return {"extra_refs": refs}


class ElemLinkIn(BaseModel):
    add: int | None = None     # 关联一个项目要素（element_id）
    remove: int | None = None  # 解除关联


@router.patch("/shots/{shot_id}/elements")
async def update_shot_elements(project_id: int, shot_id: int, body: ElemLinkIn):
    """手动增删本镜的关联要素：同步 element_ids/characters/scene_element 与出现索引，
    然后重装配提示词（零 LLM）——要素变更立即反映到提示词与参考图池。"""
    eid = body.add or body.remove
    if not eid:
        raise HTTPException(400, "缺少 add 或 remove")
    pool = get_pool()
    shot = await pool.fetchrow(
        "SELECT meta, summary FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not shot:
        raise HTTPException(404, "分镜不存在")
    elem = await pool.fetchrow(
        "SELECT id, kind, name FROM content_elements WHERE id=$1 AND project_id=$2",
        eid, project_id)
    if not elem:
        raise HTTPException(404, "要素不存在")
    meta = _jsonb(shot["meta"])
    ids = list(meta.get("element_ids") or [])
    chars = list(meta.get("characters") or [])
    scene_el = meta.get("scene_element") or ""
    if body.add:
        if elem["id"] not in ids:
            ids.append(elem["id"])
        if elem["kind"] == "character" and elem["name"] not in chars:
            chars.append(elem["name"])
        if elem["kind"] == "scene" and (not scene_el or scene_el == "无"):
            scene_el = elem["name"]
        await pool.execute(
            "INSERT INTO element_appearances (project_id, element_id, node_id, snapshot) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (element_id, node_id) DO UPDATE SET snapshot=EXCLUDED.snapshot",
            project_id, elem["id"], shot_id, meta.get("action") or (shot["summary"] or ""))
    else:
        ids = [i for i in ids if i != elem["id"]]
        chars = [c for c in chars if c != elem["name"]]
        if scene_el == elem["name"]:
            scene_el = "无"
        await pool.execute(
            "DELETE FROM element_appearances WHERE element_id=$1 AND node_id=$2", eid, shot_id)
    await pool.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps({"element_ids": ids, "characters": chars,
                             "scene_element": scene_el}, ensure_ascii=False))
    from ..services.storyboard import assemble_shot_prompts

    await assemble_shot_prompts(pool, project_id, shot_id)
    from ..services import references as reference_service
    for purpose in ("image", "video", "last"):
        await reference_service.sync_shot_from_legacy(pool, project_id, shot_id, purpose)
    return {"element_ids": ids, "characters": chars, "scene_element": scene_el}


class RefsIn(BaseModel):
    image_off: list[str] | None = None  # 首帧生成时停用的参考图名单（要素名/"故事板"）
    video_off: list[str] | None = None  # 视频生成时停用的参考图名单（含"首帧"/"尾帧"）
    last_off: list[str] | None = None   # 尾帧生成时停用的参考图名单
    # 前置条件·分镜图默认关联本镜首帧（无首帧取尾帧）；true=解除关联，那块改为空占位关键帧
    board_link_off: bool | None = None


@router.patch("/shots/{shot_id}/refs")
async def update_shot_refs(project_id: int, shot_id: int, body: RefsIn):
    """按目标（首帧/视频）独立管理参考图关联：停用的要素生成时不上传其设定图；
    视频侧停用的角色，提示词身份层自动回退外貌全文（引用与附件同生死）。"""
    shot = await get_pool().fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    ref_off = _jsonb(shot["meta"]).get("ref_off") or {}
    if body.image_off is not None:
        ref_off["image"] = body.image_off
    if body.video_off is not None:
        ref_off["video"] = body.video_off
    if body.last_off is not None:
        ref_off["last"] = body.last_off
    patch: dict[str, Any] = {"ref_off": ref_off}
    if body.board_link_off is not None:
        patch["board_link_off"] = bool(body.board_link_off)
    await get_pool().execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps(patch, ensure_ascii=False),
    )
    from ..services import references as reference_service
    for purpose in ("image", "video", "last"):
        await reference_service.sync_shot_from_legacy(get_pool(), project_id, shot_id, purpose)
    return {"ref_off": ref_off, "board_link_off": patch.get("board_link_off")}


# 提示词目标 → meta 键（last=尾帧定格：手动/AI 内容，自动装配永不触碰）
_PROMPT_KEYS = {"image": "image_prompt", "video": "video_prompt", "last": "last_image_prompt"}


class PromptSaveIn(BaseModel):
    target: str   # image | video | last
    prompt: str


@router.patch("/shots/{shot_id}/prompt")
async def save_shot_prompt(project_id: int, shot_id: int, body: PromptSaveIn):
    """保存手动编辑的提示词（弹框「保存」按钮）。双字段（2026-07-17）：
    编辑框含分隔线 → 按线拆 用户段/锚定段 各自落库，变了哪段打哪段的手编冻结标记
    （重装配只刷新未冻结段，重拼全文）；无分隔线 → 旧整段语义（全文+整段 edited 冻结）。
    显式「重生成提示词」清除全部标记回到自动装配。"""
    from ..services import prompt_fields as pf

    if body.target not in _PROMPT_KEYS:
        raise HTTPException(400, "target 必须为 image / video / last")
    if not body.prompt.strip():
        raise HTTPException(400, "提示词不能为空")
    shot = await get_pool().fetchrow(
        "SELECT id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    key = _PROMPT_KEYS[body.target]
    seg = pf.split_edit_text(body.prompt)
    if seg:
        user, anchor = seg
        meta = _jsonb(shot["meta"])
        patch: dict[str, Any] = {f"{key}_user": user, f"{key}_anchor": anchor,
                                 key: pf.compose(user, anchor),
                                 f"{key}_edited": False}  # 分段标记接管，解除旧整段冻结
        if user != (meta.get(f"{key}_user") or ""):
            patch[f"{key}_user_edited"] = True
        if anchor != (meta.get(f"{key}_anchor") or ""):
            patch[f"{key}_anchor_edited"] = True
    else:
        patch = {key: body.prompt, f"{key}_edited": True}
    await get_pool().execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps(patch, ensure_ascii=False),
    )
    return {"ok": True, key: patch[key]}


class SummarySaveIn(BaseModel):
    summary: str


@router.patch("/shots/{shot_id}/summary")
async def save_shot_summary(project_id: int, shot_id: int, body: SummarySaveIn):
    """保存手动编辑的分镜脚本正文（视频详情弹框顶部「分镜脚本」框）：更新 content_nodes.summary。
    正文是提示词装配与 AI 改写的事实边界——改后下次装配/AI 改写即以新正文为准（已手编的提示词
    带 edited 标记不受影响，需要跟随新正文时显式「重生成提示词」）。"""
    shot = await get_pool().fetchrow(
        "SELECT id FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not shot:
        raise HTTPException(404, "分镜不存在")
    summary = body.summary.strip()
    await get_pool().execute(
        "UPDATE content_nodes SET summary=$2, updated_at=now() WHERE id=$1", shot_id, summary)
    return {"ok": True, "summary": summary}


async def _chapter_script_lines(pool: Any, chapter_id: int) -> list[str]:
    """本章全部分镜脚本骨架（地点/角色/动作/对白）——AI 改写/生成提示词的事实边界。"""
    sibs = await pool.fetch(
        "SELECT summary, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
        "AND deleted_at IS NULL ORDER BY seq",
        chapter_id,
    )
    lines = []
    for s in sibs:
        m = _jsonb(s["meta"])
        lines.append(
            f"镜{m.get('shot_no')}｜{m.get('scene', '')}｜{m.get('characters') or []}｜"
            f"{m.get('action', '')}｜对白:{m.get('dialogue', '无')}｜{s['summary'] or ''}"
        )
    return lines


class PromptAiEditIn(BaseModel):
    target: str        # image | video | last
    instruction: str   # 用户的修改要求
    prompt: str | None = None  # 编辑框当前内容（可能未保存），缺省用 meta 里的


@router.post("/shots/{shot_id}/prompt/ai-edit")
async def ai_edit_prompt(project_id: int, shot_id: int, body: PromptAiEditIn):
    """AI 按要求修改提示词（同步返回，不落库——前端回填编辑框，用户确认后再保存）。
    改写以**本章分镜脚本**为事实依据：不得偏离本镜的叙事、地点与角色。"""
    from ..llm import chat_text

    if body.target not in _PROMPT_KEYS:
        raise HTTPException(400, "target 必须为 image / video / last")
    if not body.instruction.strip():
        raise HTTPException(400, "请填写修改要求")
    pool = get_pool()
    shot = await pool.fetchrow(
        "SELECT parent_id, summary, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    cur = (body.prompt or "").strip() or meta.get(_PROMPT_KEYS[body.target]) or ""
    if not cur:
        raise HTTPException(400, "尚无提示词可修改，请先生成")
    # 双字段：编辑框含分隔线 → AI 只改用户段（叙事），锚定段（结构句）原样拼回不让 AI 动
    from ..services import prompt_fields as pf

    _seg = pf.split_edit_text(cur)
    _anchor: str | None = None
    if _seg:
        cur, _anchor = _seg
    # 本章脚本上下文：全部分镜脚本骨架（地点/角色/动作/对白）——AI 修改的事实边界
    script_lines = await _chapter_script_lines(pool, shot["parent_id"])
    kind_cn = {"image": "首帧生图", "video": "视频生成", "last": "尾帧定格生图"}[body.target]
    system = (
        f"你是影视{kind_cn}提示词工程师。按用户要求修改给定提示词，只输出修改后的完整提示词，"
        "不要任何解释或前后缀。硬约束：①以下方本章分镜脚本为事实依据，本镜的地点、出场角色、"
        "动作与对白不得偏离；②保留原提示词中的结构性约束句（时间轴秒区间、角色一致性、"
        "禁文字/字幕/水印、画风锚词、时长画质）除非用户要求明确涉及；③中文为主。"
    )
    user = (
        f"【本章分镜脚本】\n" + "\n".join(script_lines)
        + f"\n\n【本镜】镜{meta.get('shot_no')}\n\n【当前{kind_cn}提示词】\n{cur}"
        + f"\n\n【修改要求】\n{body.instruction.strip()}"
    )
    try:
        out = (await chat_text(system, user, temperature=0.4)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 修改失败：{e}")
    if not out:
        raise HTTPException(502, "AI 返回为空，请重试")
    if _anchor:
        out = pf.join_for_edit(pf.strip_dividers(out), _anchor)  # 锚定段原样拼回编辑框
    return {"prompt": out}


class ApplyFrameIn(BaseModel):
    target: str   # image=首帧 / last=尾帧
    url: str


@router.post("/shots/{shot_id}/apply-frame")
async def apply_shot_frame(project_id: int, shot_id: int, body: ApplyFrameIn):
    """直接把一张图应用为本镜首帧/尾帧（跳过生成）：写 keyframe_url/last_frame_url + 落附件表。"""
    key = {"image": "keyframe_url", "last": "last_frame_url"}.get(body.target)
    src = {"image": "keyframe_source", "last": "last_frame_source"}.get(body.target)
    atype = {"image": "keyframe", "last": "last_keyframe"}.get(body.target)
    if not key:
        raise HTTPException(400, "target 必须为 image / last")
    if not (body.url or "").strip():
        raise HTTPException(400, "缺少图片 url")
    if not await get_pool().fetchval("SELECT 1 FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id):
        raise HTTPException(404, "分镜不存在")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb)",
            project_id, shot_id, body.url,
            json.dumps({"type": atype, "origin": "applied"}, ensure_ascii=False))
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps({key: body.url, src: "applied"}, ensure_ascii=False))
    return {key: body.url}


@router.post("/chapters/{node_id}/keyframes")
async def batch_keyframes(project_id: int, node_id: int, force: bool = False):
    """整章批量首帧：每镜入队 gen_keyframe（前置自动走 补设定图→重装配→质检缓存→参考图生成）。
    默认跳过已有首帧的镜；force=true 全部重出。批量视频不在此链（先人审首帧再逐镜出视频）。"""
    rows = await get_pool().fetch(
        "SELECT id, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL "
        "ORDER BY seq", node_id
    )
    tasks = []
    for r in rows:
        meta = _jsonb(r["meta"])
        if meta.get("keyframe_url") and not force:
            continue
        # 依赖 DAG：缺提示词的镜自动带出 gen_prompts 子任务，不再静默跳过
        q = await flow.enqueue_with_deps(
            get_pool(), kind="gen_keyframe", project_id=project_id, node_id=r["id"],
            payload={"prompt": meta.get("image_prompt"),
                     "prompt_overridden": bool(meta.get("image_prompt_edited")),
                     "reference_images": meta.get("reference_images") or []},
            priority=0,
        )
        tasks.append({"shot_id": r["id"], "task_id": q["task_id"]})
    return {"queued": len(tasks), "tasks": tasks}


class GroupKeyframesIn(BaseModel):
    shot_ids: list[int]           # 目标镜（前端已过滤为本页缺首帧的）
    refs: list[ExtraRef] = []     # 弹框勾选的要素参考（角色/场景设定图，可含素材库补充）
    note: str | None = None       # 组图全局要求（一致性约束句，弹框预填、用户可编辑）


@router.post("/chapters/{node_id}/keyframes/group")
async def batch_keyframes_group(project_id: int, node_id: int, body: GroupKeyframesIn):
    """整页分镜首帧·组图（Seedream sequential_image_generation，2026-07-17）：
    一个章级任务一次请求生成 N 镜首帧——组内共享上下文，角色/场景/画风一致性优于
    逐镜独立采样。缺提示词的镜由依赖 DAG 自动带出对应镜节点的 gen_prompts 子任务。
    参考图+生成数合计 ≤15（Seedream 组图硬上限）→ 一次最多 14 镜。"""
    rows = await get_pool().fetch(
        "SELECT id,meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL "
        "AND id = ANY($2::bigint[]) ORDER BY seq", node_id, body.shot_ids)
    ids = [r["id"] for r in rows]
    if not ids:
        raise HTTPException(400, "无有效目标镜（可能已被删除或不属于本章）")
    if len(ids) > 14:
        raise HTTPException(400, "组图一次最多 14 镜（参考图+生成数合计上限 15）")
    scene_keys = {
        (
            int(_jsonb(r["meta"]).get("scene_seg") or 1),
            (_jsonb(r["meta"]).get("continuity") or {}).get("scene_contract_id"),
        )
        for r in rows
    }
    if len(scene_keys) != 1:
        raise HTTPException(400, "一次组图只能包含同一场景合同的镜头；跨场景请分组生成")
    scene_seg, scene_contract_id = next(iter(scene_keys))
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_keyframes_group", project_id=project_id, node_id=node_id,
        payload={"shot_ids": ids, "refs": [r.model_dump() for r in body.refs],
                 "note": (body.note or "").strip(), "seg": scene_seg,
                 "scene_contract_id": scene_contract_id},
        priority=5,
    )


@router.post("/shots/{shot_id}/audio-precheck")
async def audio_precheck(project_id: int, shot_id: int):
    """音频预检（对白×音色，手动触发/调试用）：确定性 gate + best-effort 补小样 + LLM 评审；
    结果带指纹+有效期落 meta.audio_precheck——视频生成前置命中缓存即免重跑。永不阻断生成。"""
    from ..services.audio_precheck import precheck_shot_audio

    try:
        return await precheck_shot_audio(get_pool(), project_id, shot_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/shots/{shot_id}/keyframe")
async def gen_keyframe(project_id: int, shot_id: int):
    """生成彩色首帧关键帧（gen_video 自动以其为 I2V 首帧——画风一致性的第一锚点）。
    依赖 DAG：缺首帧提示词不再 400，自动派发 gen_prompts 子任务，完成后回调放行本任务。"""
    shot = await get_pool().fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    from ..services import references as reference_service
    refs = await reference_service.resolved_images(
        get_pool(), project_id=project_id, subject_kind="shot", subject_id=shot_id, purpose="image")
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_keyframe", project_id=project_id, node_id=shot_id,
        payload={"prompt": meta.get("image_prompt"),
                 "prompt_overridden": bool(meta.get("image_prompt_edited")),
                 "reference_images": refs},
        priority=10,
    )


@router.post("/shots/{shot_id}/last-prompt/ai")
async def gen_last_frame_prompt(project_id: int, shot_id: int):
    """AI 生成尾帧定格提示词（同步返回并落库）：以本章分镜脚本 + 本镜首帧/视频提示词为依据，
    写出「本镜结束瞬间」的定格画面。尾帧无自动装配与质检链，此端点即它的「AI 生成」入口。"""
    from ..llm import chat_text

    pool = get_pool()
    shot = await pool.fetchrow(
        "SELECT parent_id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    script_lines = await _chapter_script_lines(pool, shot["parent_id"])
    system = (
        "你是影视生图提示词工程师。为指定镜头写一条「尾帧定格画面」生图提示词——"
        "即本镜视频播放到最后一刻的静止画面。只输出提示词全文，不要任何解释。硬约束："
        "①以本章分镜脚本为事实依据，画面必须是本镜动作/切换的**收束瞬间**（最后一个切换的落点），"
        "不得偏离地点与出场角色；②沿用首帧提示词中的画风锚词、角色一致性与禁文字/字幕/水印等结构性约束；"
        "③只描述单帧静态画面（构图/景别/光线/人物姿态定格），不写运镜与时间轴；④中文为主。"
    )
    user = (
        "【本章分镜脚本】\n" + "\n".join(script_lines)
        + f"\n\n【本镜】镜{meta.get('shot_no')}"
        + f"\n\n【本镜首帧提示词】\n{meta.get('image_prompt') or '（无）'}"
        + f"\n\n【本镜视频提示词】\n{meta.get('video_prompt') or '（无）'}"
    )
    try:
        out = (await chat_text(system, user, temperature=0.4)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 生成失败：{e}")
    if not out:
        raise HTTPException(502, "AI 返回为空，请重试")
    await pool.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps({"last_image_prompt": out}, ensure_ascii=False),
    )
    return {"prompt": out}


class LastKeyframeIn(BaseModel):
    prompt: str | None = None  # 允许弹框编辑后的提示词覆盖（缺省用 meta.last_image_prompt）


@router.post("/shots/{shot_id}/last-keyframe")
async def gen_last_keyframe(project_id: int, shot_id: int, body: LastKeyframeIn | None = None):
    """生成尾帧定格画面（可选）：与首帧同路径生图（设定图参考+引用句），产物写 meta.last_frame_url。
    视频提交时 media 层折算为 reference_image + 「结尾落在@图片N」引用句，不占 last_frame 通道。
    尾帧无自动装配链：缺提示词直接 400（先在尾帧卡手写或 AI 生成）。"""
    shot = await get_pool().fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    prompt = (body.prompt if body and body.prompt else None) or meta.get("last_image_prompt")
    if not prompt:
        raise HTTPException(400, "请先填写或 AI 生成尾帧提示词")
    return await flow.enqueue(
        get_pool(), kind="gen_last_keyframe", project_id=project_id, node_id=shot_id,
        payload={"prompt": prompt, "prompt_overridden": True,
                 "reference_images": meta.get("reference_images") or []},
        priority=10,
    )


class NeighborFrameIn(BaseModel):
    target: str  # first=取上一镜视频尾帧→本镜首帧；last=取下一镜视频首帧→本镜尾帧


@router.post("/shots/{shot_id}/frame-from-neighbor")
async def frame_from_neighbor(project_id: int, shot_id: int, body: NeighborFrameIn):
    """从相邻镜视频抽帧作本镜首/尾帧（同步端点，抽帧秒级不入队）：
    target=first 抽上一镜视频最后一帧写 meta.keyframe_url（与上镜收尾无缝衔接）；
    target=last 抽下一镜视频第一帧写 meta.last_frame_url（收束到下镜开场）。
    抽帧结果转存 OSS，meta 同时记 keyframe_source/last_frame_source 区分「抽取」与「生成」。"""
    if body.target not in ("first", "last"):
        raise HTTPException(400, "target 需为 first 或 last")
    pool = get_pool()
    shot = await pool.fetchrow(
        "SELECT parent_id, seq, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    prev = body.target == "first"
    if prev:
        neighbor = await pool.fetchrow(
            "SELECT id, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND seq<$2 "
            "AND deleted_at IS NULL ORDER BY seq DESC LIMIT 1", shot["parent_id"], shot["seq"])
    else:
        neighbor = await pool.fetchrow(
            "SELECT id, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND seq>$2 "
            "AND deleted_at IS NULL ORDER BY seq LIMIT 1", shot["parent_id"], shot["seq"])
    if not neighbor:
        raise HTTPException(400, "本镜没有上一镜，无法抽取" if prev else "本镜没有下一镜，无法抽取")
    video_url = _jsonb(neighbor["meta"]).get("video_url")
    if not video_url:
        raise HTTPException(400, ("上一镜" if prev else "下一镜") + "还没有生成视频，请先生成后再抽帧")
    from .. import oss
    from ..services.frames import extract_frame

    try:
        content = await extract_frame(video_url, "last" if prev else "first")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"抽帧失败：{e}")
    url = await oss.store_bytes(content, "keyframe", ".jpeg")
    if not url:
        raise HTTPException(502, "OSS 未配置或转存失败，抽帧结果无法保存")
    patch = ({"keyframe_url": url, "keyframe_source": "prev_video"} if prev
             else {"last_frame_url": url, "last_frame_source": "next_video"})
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb)",
            project_id, shot_id, url,
            json.dumps({"type": "keyframe" if prev else "last_keyframe",
                        "from": "neighbor_video", "neighbor_shot_id": neighbor["id"]},
                       ensure_ascii=False),
        )
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps(patch, ensure_ascii=False),
        )
    return {"url": url, "neighbor_shot_id": neighbor["id"]}


@router.post("/shots/{shot_id}/frame-from-video")
async def frame_from_video(
    project_id: int,
    shot_id: int,
    target: str = Form(...),          # first=写本镜首帧 / last=写本镜尾帧
    at_sec: float = Form(...),        # 抽取时间点（秒）——前端 <video> 拖轴/逐帧定位后回传
    video_url: str | None = Form(None),  # 已有视频（本镜/邻镜）URL；与 file 二选一
    file: UploadFile | None = File(None),  # 临时上传的视频文件；与 video_url 二选一
):
    """按时间点从视频抽一帧作本镜首/尾帧（同步端点，抽帧秒级不入队）：
    前端 <video> 承担播放/拖轴/慢放/逐帧交互，点「就用这一帧」时把 currentTime 作为 at_sec 回传，
    后端 ffmpeg 按时间戳精确抽全分辨率帧、转存 OSS，meta 记 source=extracted 区分「抽取」与「生成」。
    视频源可为已有 URL（video_url）或临时上传文件（file）——上传件抽完即删，不落库。"""
    if target not in ("first", "last"):
        raise HTTPException(400, "target 需为 first 或 last")
    if not (video_url or "").strip() and file is None:
        raise HTTPException(400, "需提供 video_url 或上传 file")
    if not await get_pool().fetchval(
        "SELECT 1 FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id):
        raise HTTPException(404, "分镜不存在")
    from .. import oss
    from ..services.frames import extract_frame

    tmp_path: str | None = None
    try:
        if file is not None:
            import tempfile
            from pathlib import Path
            data = await file.read()
            if not data:
                raise HTTPException(400, "上传的视频为空")
            suffix = Path(file.filename or "").suffix or ".mp4"
            tf = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tf.write(data)
            tf.close()
            tmp_path = tf.name
            src = tmp_path
        else:
            src = video_url  # type: ignore[assignment]
        try:
            content = await extract_frame(src, "first", at_sec=max(at_sec, 0.0))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"抽帧失败：{e}")
    finally:
        if tmp_path:
            from pathlib import Path
            Path(tmp_path).unlink(missing_ok=True)
    url = await oss.store_bytes(content, "keyframe", ".jpeg")
    if not url:
        raise HTTPException(502, "OSS 未配置或转存失败，抽帧结果无法保存")
    first = target == "first"
    patch = ({"keyframe_url": url, "keyframe_source": "extracted"} if first
             else {"last_frame_url": url, "last_frame_source": "extracted"})
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb)",
            project_id, shot_id, url,
            json.dumps({"type": "keyframe" if first else "last_keyframe",
                        "from": "video_scrub", "at_sec": round(max(at_sec, 0.0), 3)},
                       ensure_ascii=False),
        )
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps(patch, ensure_ascii=False),
        )
    return {"url": url}


class VideoIn(BaseModel):
    prompt: str | None = None  # 允许前端编辑后的提示词覆盖


@router.post("/shots/{shot_id}/video")
async def gen_video(project_id: int, shot_id: int, body: VideoIn | None = None):
    """点击提示词→异步生成本镜视频。前置守卫（worker 侧 VideoStep.before）：
    ①要素设定图（指纹缓存）②提示词质检状态（缓存命中免重跑）③音频预检（缓存，永不阻断）。
    依赖 DAG：缺视频提示词/首帧不再 400——自动派发 gen_prompts / gen_keyframe 子任务
    （首帧又缺提示词则再向上派发，幂等去重合并公共依赖），全部完成后回调放行本任务。"""
    shot = await get_pool().fetchrow(
        "SELECT parent_id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
    )
    if not shot:
        raise HTTPException(404, "分镜不存在")
    meta = _jsonb(shot["meta"])
    prompt = (body.prompt if body and body.prompt else None) or meta.get("video_prompt")
    # 画幅比例：本镜所属卷的 aspect_ratio（卷未覆盖则继承项目）。
    # 首帧策略：VideoStep.before 提交前按 meta.keyframe_url 实时刷新（依赖子任务出的
    # 首帧要能被用上），黑白故事板永不作首帧；此处不再固化 first_frame_url。
    proj = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    eff = await volumes.effective_for_chapter(get_pool(), proj, shot["parent_id"]) if proj else {}
    ratio = (eff.get("config") or {}).get("aspect_ratio") or "16:9"
    payload = {
        "prompt": prompt,
        # 手编提示词（请求体覆盖 / 弹框保存的 edited 标记）：前置重装配与质检重构均不覆盖
        "prompt_overridden": bool(body and body.prompt) or bool(meta.get("video_prompt_edited")),
        # 纯文本兜底版（身份层=外貌全文）：降级链走到"无任何输入图"时用它
        "prompt_textonly": meta.get("video_prompt_textonly") or prompt,
        "duration_s": meta.get("duration_s", 5),
        "ratio": ratio,
        "reference_images": meta.get("reference_images") or [],
    }
    return await flow.enqueue_with_deps(
        get_pool(), kind="gen_video", project_id=project_id, node_id=shot_id,
        payload=payload, priority=10,
    )


# ═══════════════ 任务查询 / 取消 / 重试 / SSE 事件流 ═══════════════

@router.get("/tasks/{task_id}")
async def task_status(project_id: int, task_id: int):
    r = await get_pool().fetchrow("SELECT * FROM task_queue WHERE id=$1", task_id)
    if not r:
        raise HTTPException(404, "任务不存在")
    d = dict(r)
    d["payload"] = _jsonb(d["payload"])
    d["result"] = _jsonb(d["result"]) if d["result"] else None
    return d


@router.get("/tasks")
async def list_tasks(project_id: int):
    """项目任务列表（依赖 DAG 摘要口径）：在途全量 + 最近 30 条已结束，
    含 parents 依赖边 / deps_remaining / 节点标注（镜号/标题）——任务队列面板与刷新恢复用。"""
    return await flow.fetch_task_summaries(get_pool(), project_id)


def _sse(data: Any) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/events")
async def task_events(project_id: int):
    """SSE 实时事件流（长连接）：任务状态每次转移 / 流式拆镜逐镜产出 / 拆镜清场。
    连接即发全量任务快照（type=snapshot），此后增量推送（type=task/shot/shots_reset）；
    15s 心跳注释保活。EventSource 断线自动重连，重连再发快照收敛丢失事件。"""
    pool = get_pool()

    async def gen():
        yield _sse({"type": "snapshot", "tasks": await flow.fetch_task_summaries(pool, project_id)})
        with events.subscribe(project_id) as q:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # nginx 反代不缓冲——SSE 实时性必需
    })


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(project_id: int, task_id: int):
    """取消任务：pending/waiting_deps（排队/等前置）与 waiting_external（放弃收割）可取消；
    running 不可。取消会连锁使等待它的父任务 failed（前置被取消，盲跑无意义）。"""
    r = await get_pool().fetchrow(
        "UPDATE task_queue SET status='canceled', finished_at=now() "
        "WHERE id=$1 AND status IN ('pending','waiting_deps','waiting_external') "
        "RETURNING node_id, kind", task_id,
    )
    if not r:
        raise HTTPException(409, "任务不存在或已在执行/已结束，无法取消")
    step = flow.STEPS.get(r["kind"])
    if step:
        await flow.set_gen_state(get_pool(), r["node_id"], step.gen_slot, "canceled", task_id)
    await flow.notify_task(get_pool(), task_id)
    await flow.fail_parents(get_pool(), task_id, r["kind"])
    return {"ok": True}


@router.post("/tasks/{task_id}/retry")
async def retry_task(project_id: int, task_id: int):
    """手动重试：failed 任务重新入队（attempt 归零、新任务记 retry_of 便于对比）。
    走依赖解析——前置产物仍缺（如因前置失败被连锁 blocked）会自动重新派发子任务。"""
    r = await get_pool().fetchrow(
        "SELECT * FROM task_queue WHERE id=$1 AND status='failed'", task_id
    )
    if not r:
        raise HTTPException(409, "任务不存在或未失败，无需重试")
    payload = _jsonb(r["payload"])
    payload.pop("attempts", None)
    payload["retry_of"] = task_id
    return await flow.enqueue_with_deps(
        get_pool(), kind=r["kind"], project_id=r["project_id"], node_id=r["node_id"],
        payload=payload, priority=10,
    )


class SkillRunIn(BaseModel):
    instruction: str = ""
    context: dict[str, Any] | None = None


@router.post("/canvas/skills/{slug}/run")
async def run_canvas_skill(project_id: int, slug: str, body: SkillRunIn):
    """画布技能节点执行：按 SKILL.md（含 references 渐进披露）处理画布上下文。"""
    from ..services import canvas_skills
    try:
        return await canvas_skills.run_skill(
            get_pool(), slug, body.instruction, body.context)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class CanvasAgentIn(BaseModel):
    instruction: str
    canvas: dict[str, Any]


@router.post("/canvas/agent")
async def canvas_agent(project_id: int, body: CanvasAgentIn):
    """画布 Agent：读画布全局状态 + 指令 → 返回可执行的画布操作序列。"""
    from ..services import canvas_skills
    if not body.instruction.strip():
        raise HTTPException(400, "请先输入指令")
    try:
        return await canvas_skills.plan_canvas(get_pool(), body.instruction, body.canvas)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
