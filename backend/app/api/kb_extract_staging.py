"""知识提炼页临时上传/暂存接口（测试用，非正式功能）。

用途：cankao_knowledge.html 里手动为每个知识块上传素材（视频/封面/图片/音频），
上传后转存到 OSS，再把「块id -> 素材url」的对应关系写到本地临时 JSON 文件——
不落数据库，因为这批数据后续要整个删掉，写文件方便直接查看/清空。
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from .. import oss

log = logging.getLogger("kb_extract_staging")

router = APIRouter(prefix="/api/test/kb-extract", tags=["kb-extract-staging"])

_STAGING_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "tmp" / "kb_extract_staging.json"


def _read_staging() -> dict:
    if not _STAGING_FILE.exists():
        return {}
    try:
        return json.loads(_STAGING_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _write_staging(data: dict) -> None:
    _STAGING_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STAGING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/upload")
async def upload(file: UploadFile = File(...), block_id: str = Form(...), slot: str = Form(...)):
    """上传单个素材文件（视频/封面/图片/音频），转存 OSS，返回 url。"""
    data = await file.read()
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    url = await oss.store_bytes(data, prefix="kb-extract-staging", ext=ext or ".bin")
    return {"ok": bool(url), "url": url, "block_id": block_id, "slot": slot}


@router.get("/save")
async def get_staging():
    """读取当前暂存的 块id -> 素材 对应关系，供页面刷新后回填。"""
    return _read_staging()


@router.post("/save")
async def save_staging(body: dict):
    """把 {block_id: {slot: url, ...}, ...} 合并写入本地临时文件（不入库）。"""
    current = _read_staging()
    for block_id, slots in body.items():
        current.setdefault(block_id, {})
        current[block_id].update(slots)
    _write_staging(current)
    return {"ok": True, "path": str(_STAGING_FILE)}
