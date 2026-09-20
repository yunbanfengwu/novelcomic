"""Project material ingestion helpers.

The first pass intentionally keeps extraction local and deterministic.  Plain
text/Markdown/CSV/JSON are decoded directly; DOCX and PDF are handled when
their small optional readers are installed.  The resulting chunks are useful
to later outline/episode agents and can be reprocessed without re-uploading.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    # Preserve paragraph boundaries before stripping tags.
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").strip()


def extract_text(filename: str, data: bytes, content_type: str | None = None) -> tuple[str, str]:
    """Return ``(text, extractor)`` and never fail an upload on an unknown type."""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx" or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            return _docx_text(data), "docx-xml"
        except Exception:
            return _decode(data), "fallback-decode"
    if suffix == ".pdf" or content_type == "application/pdf":
        try:
            from pypdf import PdfReader  # type: ignore
            pages = PdfReader(io.BytesIO(data)).pages
            return "\n\n".join((p.extract_text() or "") for p in pages).strip(), "pypdf"
        except Exception:
            return _decode(data), "fallback-decode"
    text = _decode(data)
    if suffix in {".html", ".htm"}:
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    return text.strip(), "text-decode"


def chunk_text(text: str, max_chars: int = 6000, overlap: int = 240) -> list[dict[str, Any]]:
    """Split on paragraph/sentence boundaries while retaining small overlap."""
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    if not text:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + max_chars)
        if end < n:
            candidates = [text.rfind(mark, start, end) for mark in ("\n\n", "\n", "。", "！", "？", ".", "!", "?")]
            boundary = max(candidates)
            if boundary > start + max_chars // 2:
                end = boundary + (1 if text[boundary] == "。" else 0)
        body = text[start:end].strip()
        if body:
            chunks.append({"index": len(chunks), "content": body,
                           "summary": re.sub(r"\s+", " ", body)[:360],
                           "char_start": start, "char_end": end,
                           "char_count": len(body)})
        if end >= n:
            break
        start = max(start + 1, end - overlap)
    return chunks


def core_excerpt(text: str, limit: int = 1800) -> str:
    """Cheap deterministic fallback used before an LLM summary is available."""
    lines = [re.sub(r"\s+", " ", x).strip() for x in (text or "").splitlines()]
    headings = [x for x in lines if x and (x.startswith(("#", "第", "一、", "二、", "三、")) or len(x) < 48)]
    seed = "\n".join(dict.fromkeys(headings[:12]))
    return (seed + ("\n" if seed else "") + re.sub(r"\s+", " ", text or "")).strip()[:limit]
