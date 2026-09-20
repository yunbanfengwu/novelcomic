"""文档摄取 / 混合检索 API（2026-09-17 新增，纯增量）。

kb_entries 单表原则不变：整篇文档解析分块后以 kind='doc_chunk' 落同一张表，
来源追溯靠 source_name/source_hash/chunk_seq（98 号迁移）。
检索与 agent 工具 kb.search 共用 services.kb_ingest.search_entries 一份实现。
"""
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..db import get_pool
from ..services import kb_ingest
from ..users import current_user
from .kb_library import _jsonb  # 复用同一套 jsonb 归一化

router = APIRouter(prefix="/api/kb/doc", tags=["kb-doc"])


class IngestBody(BaseModel):
    """JSON 直传摄取（文本已在手里、不走文件上传时用）。"""
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    scope: str = Field(default="project", pattern="^(global|project)$")
    project_id: int | None = None
    folder_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    max_chars: int = Field(default=800, ge=100, le=8000)
    overlap: int = Field(default=120, ge=0, le=400)


@router.post("/ingest")
async def ingest(body: IngestBody, user: dict = Depends(current_user)) -> dict:
    """整篇文本入库：分块 + 向量（可用时）+ source_hash 幂等重建。"""
    if body.scope == "project" and not body.project_id:
        raise HTTPException(422, "项目级文档必须提供 project_id")
    result = await kb_ingest.ingest_document(
        get_pool(), title=body.title, text=body.text,
        source_name=body.title, scope=body.scope, project_id=body.project_id,
        folder_id=body.folder_id, tags=body.tags,
        max_chars=body.max_chars, overlap=body.overlap)
    return {**result, "scope": body.scope, "project_id": body.project_id}


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    scope: str = Form(default="project"),
    project_id: int | None = Form(default=None),
    folder_id: int | None = Form(default=None),
    tags: str = Form(default=""),
    max_chars: int = Form(default=800),
    overlap: int = Form(default=120),
    user: dict = Depends(current_user),
) -> dict:
    """文件上传摄取：内置 txt/md/docx/html/json/csv；pdf 需 requirements 补 pypdf。"""
    if scope not in ("global", "project"):
        raise HTTPException(422, "scope 只能是 global 或 project")
    if scope == "project" and not project_id:
        raise HTTPException(422, "项目级文档必须提供 project_id")
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "文件超过 20MB 上限")
    filename = file.filename or "未命名.txt"
    try:
        text = kb_ingest.parse_document(filename, data)
    except ImportError as e:
        raise HTTPException(422, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    text = text.strip()
    if not text:
        raise HTTPException(422, "解析后没有可用文本（扫描版 PDF 请先 OCR）")
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    result = await kb_ingest.ingest_document(
        get_pool(), title=filename.rsplit(".", 1)[0], text=text,
        source_name=filename, scope=scope, project_id=project_id,
        folder_id=folder_id, tags=tag_list,
        max_chars=max(100, int(max_chars or 800)),
        overlap=max(0, int(overlap or 120)))
    return {**result, "file": filename, "chars": len(text)}


@router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=500),
    project_id: int | None = None,
    folder_ids: str = "",
    kinds: str = "doc_chunk",
    content_type: str | None = None,
    top_k: int = Query(default=8, ge=1, le=20),
) -> dict:
    """混合检索（向量+trgm+ILIKE 融合），kinds 传空串=全部类型。"""
    folder_list = [int(x) for x in folder_ids.split(",") if x.strip().isdigit()]
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] or None
    hits = await kb_ingest.search_entries(
        get_pool(), q, folder_ids=folder_list, project_id=project_id,
        kinds=kind_list, content_type=content_type, top_k=top_k)
    return {"query": q, "hits": hits, "hit_count": len(hits)}


@router.get("/{source_hash}")
async def doc_chunks(source_hash: str, project_id: int | None = None) -> dict:
    """按来源 hash 查看整篇分块（前端文档详情/核对切块质量用）。"""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id,name,title,description,content,chunk_seq,source_name,enabled,meta "
        "FROM kb_entries WHERE kind='doc_chunk' AND source_hash=$1 "
        "AND ($2::bigint IS NULL OR project_id=$2) ORDER BY chunk_seq",
        source_hash, project_id)
    if not rows:
        raise HTTPException(404, f"来源 {source_hash[:12]}… 不存在")
    chunks = []
    for r in rows:
        item = dict(r)
        item["meta"] = _jsonb(item.get("meta"))
        chunks.append(item)
    return {"source_hash": source_hash, "source_name": chunks[0]["source_name"],
            "chunk_count": len(chunks), "chunks": chunks}


@router.delete("/{source_hash}")
async def delete_doc(source_hash: str, project_id: int | None = None,
                     user: dict = Depends(current_user)) -> dict:
    """按来源 hash 整篇下架（enabled=false，可恢复）；global 文档仅管理员角色可删。"""
    pool = get_pool()
    if not project_id and user.get("role") != "admin":
        raise HTTPException(403, "公共文档下架需要 admin 角色")
    n = await pool.fetchval(
        "WITH moved AS (UPDATE kb_entries SET enabled=FALSE "
        "WHERE kind='doc_chunk' AND source_hash=$1 "
        "AND ($2::bigint IS NULL OR project_id=$2) RETURNING 1) "
        "SELECT count(*) FROM moved", source_hash, project_id)
    return {"disabled_chunks": n or 0}
