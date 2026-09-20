"""素材库直生成（新增素材弹框「生成图片/生成视频」tab）：提示词两开关装配 + 素材视频同步生成落库。

两开关（前端左下角勾选）：
- use_project 参考项目总体设定：注入项目年代/世界观锚（含画风名兜底，见 element_sheet._world_clause）；
- use_kb 采用系统知识构建：按项目画风召回知识库画风块，图片再织入通用质量词（经 assemble_image_prompt）；
- 两开关全关 = 纯享模式：提示词原样直达大模型，不注入任何项目/知识库因素。
  参考图仍走 media 层原有链路——Seedance 2.0 下角色库已 Active 的角色自动换 asset:// 可信素材。
"""
import asyncio
import json
from typing import Any

import asyncpg

from ..knowledge import assemble_image_prompt, get_block, recall_blocks
from .element_sheet import _world_clause


async def assemble_asset_prompt(
    pool: asyncpg.Pool, project: asyncpg.Record, user_prompt: str,
    *, use_project: bool, use_kb: bool, media: str,
) -> str:
    """按两开关装配最终提示词；全关（纯享模式）原样返回。"""
    if not (use_project or use_kb):
        return user_prompt
    subject = user_prompt
    if use_project:
        subject = f"{subject.rstrip('。 ')}。{_world_clause(project)}"
    if not use_kb:
        return subject
    async with pool.acquire() as conn:
        style_blocks = await recall_blocks(
            conn, project["art_style"] or "日漫", ["style"], project["id"], top_k=1)
        quality = await get_block(conn, "quality", "通用质量词") if media == "image" else None
    if media != "image":
        # 视频：只前置画风块的视觉质感子句（质量词是生图词表，不塞给 Seedance）
        bits = [b.get("positive") or b.get("content") or "" for b in style_blocks]
        bits = [b for b in bits if b]
        return f"画面风格：{'; '.join(bits)}。{subject}" if bits else subject
    blocks = [b for b in [*style_blocks, quality] if b]
    positive, _neg = assemble_image_prompt(blocks, subject)  # Seedream 只吃 positive
    return positive


async def generate_video_asset(
    pool: asyncpg.Pool, project_id: int, prompt: str,
    refs: list[dict[str, Any]] | None, *, ratio: str, duration: int = 5,
    store_dir: str = "asset_video", meta_type: str = "asset", display_name: str | None = None,
    node_id: int | None = None, resolution: str | None = None,
) -> dict[str, Any]:
    """同步生成一段素材视频并落库（调用方需已设置 media.GEN_AUDIT 上下文）。

    ARK Seedance = 提交异步任务 + 本请求内轮询收割（该任务不进 flow 队列，poller 不接手，
    审计闭环由这里按 external_task_id 回写 done/failed）；GRSAI = 纯文生视频阻塞返回。
    结果 OSS 永久化后落 content_attachments（kind=video, meta.type=asset, origin=gen），
    素材库「视频」分组即可见。refs 经 submit_ark_video 原链路——角色库 Active 自动换 asset://。
    store_dir/meta_type/display_name：先导预告片等衍生用途换 OSS 目录与附件类型标记，默认素材视频。
    """
    from .. import media, oss

    if await media.video_provider_is_ark():
        task_id = await media.submit_ark_video(
            prompt, reference_images=refs or None, duration=duration, ratio=ratio,
            resolution=resolution)
        url: str | None = None
        for _ in range(240):
            await asyncio.sleep(3)
            res = await media.check_ark_video(task_id)
            if res["status"] == "done":
                url = res["video_url"]
                break
            if res["status"] == "failed":
                await pool.execute(
                    "UPDATE gen_logs SET status='failed', error=$2, finished_at=now() "
                    "WHERE external_task_id=$1 AND status='accepted'",
                    task_id, str(res.get("error") or "")[:500])
                raise RuntimeError(f"视频生成失败：{res.get('error')}")
        if not url:
            raise TimeoutError(f"视频任务 {task_id} 轮询超时（服务端已提交，稍后可在生成日志查看）")
        stored = await oss.store_url(url, f"{store_dir}/{project_id}") or url
        await pool.execute(
            "UPDATE gen_logs SET status='done', result=$2::jsonb, finished_at=now() "
            "WHERE external_task_id=$1 AND status='accepted'",
            task_id, json.dumps({"video_url": stored}, ensure_ascii=False))
    else:
        r = await media.generate_video(prompt, duration=duration, ratio=ratio)
        stored = await oss.store_url(r["url"], f"{store_dir}/{project_id}") or r["url"]
    att = await pool.fetchrow(
        "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
        "VALUES ($1,$2,'video',$3,$4::jsonb) RETURNING id",
        project_id, node_id, stored,
        json.dumps({"type": meta_type, "origin": "gen", "prompt": prompt,
                    **({"resolution": resolution} if resolution else {}),
                    **({"name": display_name} if display_name else {})}, ensure_ascii=False))
    return {"id": att["id"], "name": display_name or f"素材视频{att['id']}",
            "kind": "video", "url": stored}
