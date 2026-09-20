"""文档摄取 + 混合检索（2026-09-17 新增，纯增量，零新依赖）。

P1 补强：把"上传一篇文档"变成知识库条目——
解析（内置 txt/md/docx/html/json/csv；pdf 走可选依赖，缺包给出明确提示）→
切块（标题/段落感知 + 句子边界兜底，块长/重叠可配）→ 批量向量（失败自动降级）→
写 kb_entries(kind='doc_chunk')，按 source_hash 幂等重建（同文档重复上传=整篇更新）。

检索侧只此一家 `search_entries`：agent 的 kb.search 工具与前端画布检索共用，
pgvector + pg_trgm + ILIKE 三级融合，任一级缺席自动降级，绝不阻断生成。

为什么不引 LlamaIndex/RAGFlow：摄取本质是"解析器 + 切块器 + 三条 SQL"，
为读一篇文档拉一棵依赖树不值；解析器留了插件位，requirements 补 pypdf 后即启用。
"""
from __future__ import annotations

import hashlib
import html.parser
import io
import json
import re
import zipfile
from typing import Any

import asyncpg

from .. import embeddings


# ── SQL 参数构造器：n 个动态片段拼参数时保证 $n 永不错位 ────────────────────

class Params:
    """按添加顺序生成 $1/$2/… 占位符；SQL 片段任意拼接顺序都安全。"""

    def __init__(self) -> None:
        self.values: list[Any] = []

    def add(self, value: Any) -> str:
        self.values.append(value)
        return f"${len(self.values)}"


# ── 解析：filename + bytes → 纯文本（零依赖；pdf 可选依赖）─────────────────

class _HTMLText(html.parser.HTMLParser):
    _BREAK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:  # noqa: ARG002
        if tag in self._BREAK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def parse_html(text: str) -> str:
    parser = _HTMLText()
    parser.feed(text)
    return "".join(parser.parts)


def parse_docx(data: bytes) -> str:
    """docx=zip 里的 word/document.xml：抽 <w:t> 文本，段落边界用 </w:p>。零依赖。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError(f"不是有效的 .docx 文件：{e}") from e
    paragraphs: list[str] = []
    for para_xml in xml.split("</w:p>"):
        runs = re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", para_xml, re.DOTALL)
        if runs:
            paragraphs.append("".join(runs))
    text = "\n".join(paragraphs)
    for esc, raw in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                     ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(esc, raw)
    return text


def parse_pdf(data: bytes) -> str:
    """pdf 走可选依赖；没装时给一句能落地的提示，不静默返回空。"""
    try:
        import pypdf  # noqa: PLC0415 — 可选依赖，requirements 补装后启用
    except ImportError as first_err:
        try:
            import PyPDF2  # type: ignore[no-redef]  # noqa: PLC0415
        except ImportError:
            raise ImportError(
                "PDF 解析需要 pypdf：请在可信环境 `pip install pypdf` 并写入 "
                "backend/requirements.txt（本次补强约定零新依赖，故未内置）") from first_err
        reader = PyPDF2.PdfReader(io.BytesIO(data))
    else:
        reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def decode_text(data: bytes) -> str:
    """上传文本兜底解码：utf-8 优先，失败退 gbk，再失败替换符硬解（绝不抛错）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_document(filename: str, data: bytes) -> str:
    """按扩展名分发解析；未知扩展当纯文本。"""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix == ".docx":
        return parse_docx(data)
    if suffix == ".pdf":
        return parse_pdf(data)
    if suffix in (".html", ".htm"):
        return parse_html(decode_text(data))
    if suffix == ".json":
        raw = decode_text(data)
        try:
            obj = json.loads(raw)
            if isinstance(obj, (list, dict)):
                return json.dumps(obj, ensure_ascii=False, indent=1)
        except json.JSONDecodeError:
            pass
        return raw
    return decode_text(data)


# ── 分块：标题/段落感知 + 句子边界兜底（纯函数，max_chars 是硬上限）─────────

def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """超长段落按句子边界切；单句仍超长才按字符硬切。"""
    sentences = [s for s in re.split(r"(?<=[。！？!?])", paragraph) if s.strip()]
    blocks: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if buf:
                blocks.append(buf)
                buf = ""
            blocks.extend(sentence[i:i + max_chars]
                          for i in range(0, len(sentence), max_chars))
            continue
        if buf and len(buf) + len(sentence) > max_chars:
            blocks.append(buf)
            buf = sentence
        else:
            buf += sentence
    if buf:
        blocks.append(buf)
    return blocks


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 120) -> list[str]:
    """把整篇文档切成知识块。确定性规则，无模型参与：
    - 段落累计不超 max_chars；Markdown 标题（# 开头）强制起新块；
    - 单段超长 → 句子边界再切；
    - 相邻块带 overlap 字符重叠（只一块时无重叠），保住跨块上下文。"""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    max_chars = max(100, max_chars)
    overlap = max(0, min(overlap, max_chars // 2))

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    blocks: list[str] = []
    buf = ""
    for para in paragraphs:
        if re.match(r"^#{1,6}\s", para) and buf:  # Markdown 标题=硬边界
            blocks.append(buf)
            buf = ""
        if len(para) > max_chars:
            if buf:
                blocks.append(buf)
                buf = ""
            pieces = _split_long_paragraph(para, max_chars)
            blocks.extend(pieces[:-1])
            buf = pieces[-1] if pieces else ""
            continue
        if buf and len(buf) + len(para) + 1 > max_chars:
            blocks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        blocks.append(buf)

    if overlap and len(blocks) > 1:
        # 链式重叠：后块头部带前一**最终块**的尾部 overlap 字符——
        # 任意相邻两块都有 overlap 字符的连续重叠，跨块上下文不断链
        overlapped = [blocks[0]]
        for b in blocks[1:]:
            overlapped.append(overlapped[-1][-overlap:] + b)
        blocks = overlapped
    return [b.strip() for b in blocks if b and b.strip()]


def source_fingerprint(text: str) -> str:
    """整篇文档 sha256：同 hash 重复摄取=幂等重建。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ── 摄取：分块 → 向量 → 落库（source_hash 幂等重建）────────────────────────

async def _embed_col_exists(conn: asyncpg.Connection) -> bool:
    """kb_entries 是否有 embedding 列（无 pgvector 环境为 False）。同 knowledge.py 策略。"""
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='kb_entries' AND column_name='embedding'"))


def _to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def ingest_document(
    pool: asyncpg.Pool, *, title: str, text: str,
    source_name: str | None = None, scope: str = "project",
    project_id: int | None = None, folder_id: int | None = None,
    tags: list[str] | None = None, max_chars: int = 800, overlap: int = 120,
) -> dict[str, Any]:
    """整篇入库。向量服务不可用时降级为纯文本块落库（检索走 trgm），绝不抛错中断。"""
    title = (title or "").strip() or (source_name or "未命名文档")
    if scope == "project" and not project_id:
        raise ValueError("项目级文档必须给 project_id")
    text = text or ""
    doc_hash = source_fingerprint(text)
    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    if not chunks:
        return {"source_hash": doc_hash, "chunks": 0, "embedded": 0, "entry_ids": []}

    vectors: list[list[float]] | None = None
    try:
        vectors = await embeddings.embed(chunks)
    except Exception:  # noqa: BLE001 — 嵌入缺席降级
        vectors = None

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "DELETE FROM kb_entries WHERE kind='doc_chunk' AND source_hash=$1 "
            "AND (scope='global' OR ($2::bigint IS NOT NULL AND project_id=$2))",
            doc_hash, project_id)
        has_embed = await _embed_col_exists(conn)
        ids: list[int] = []
        for seq, chunk in enumerate(chunks):
            p = Params()
            vec = vectors[seq] if vectors and seq < len(vectors) else None
            embed_sql = ""
            if has_embed and vec:
                embed_sql = f",{p.add(_to_pgvector(vec))}::vector"
            row = await conn.fetchrow(
                f"""
                INSERT INTO kb_entries(scope,project_id,folder_id,kind,category,
                    name,title,description,content,tags,source_name,source_hash,
                    chunk_seq{',embedding' if embed_sql else ''})
                VALUES({p.add(scope)},{p.add(project_id)},{p.add(folder_id)},
                    {p.add('doc_chunk')},NULL,{p.add(title)},
                    {p.add(f'{title} · {seq + 1}/{len(chunks)}')},
                    {p.add(f'文档《{title}》第 {seq + 1}/{len(chunks)} 块')},
                    {p.add(chunk)},{p.add(tags or [])},
                    {p.add(source_name)},{p.add(doc_hash)},{p.add(seq)}{embed_sql})
                RETURNING id
                """,
                *p.values)
            ids.append(row["id"])
    return {"source_hash": doc_hash, "chunks": len(chunks),
            "embedded": len(vectors) if vectors else 0, "entry_ids": ids}


# ── 混合检索：pgvector + trgm 双路召回，Python 侧融合 ───────────────────────

def fuse_scores(vec_hits: list[dict[str, Any]], trgm_hits: list[dict[str, Any]],
                top_k: int = 8) -> list[dict[str, Any]]:
    """两路召回按 id 合并：score = 0.6*向量相似 + 0.4*trgm 相似（单路命中取单路分）。

    与 knowledge.recall_blocks 的 0.6/0.4 配比一致；并列时 chunk_seq 小者优先
    （文档从头往后读更自然），再按 id 稳定排序。
    """
    by_id: dict[Any, dict[str, Any]] = {}
    for row in vec_hits:
        item = dict(row)
        item["vec_sim"] = float(item.pop("sim", 0.0) or 0.0)
        item["trgm_sim"] = 0.0
        by_id[item["id"]] = item
    for row in trgm_hits:
        if row["id"] in by_id:
            by_id[row["id"]]["trgm_sim"] = float(row.get("sim", 0.0) or 0.0)
        else:
            item = dict(row)
            item["vec_sim"] = 0.0
            item["trgm_sim"] = float(item.pop("sim", 0.0) or 0.0)
            by_id[item["id"]] = item
    merged = [{**item, "score": round(0.6 * item["vec_sim"] + 0.4 * item["trgm_sim"], 6)}
              for item in by_id.values()]
    merged.sort(key=lambda r: (-r["score"], r.get("chunk_seq") if r.get("chunk_seq") is not None else 1 << 30, r["id"]))
    return merged[: max(1, top_k)]


def folder_where(folders: list[asyncpg.Record], params: Params) -> str:
    """kb_folders 行 → WHERE 片段。系统文件夹按 (kind,category) 规则圈定，
    自定义文件夹按 folder_id 归属（与 agent_runtime._folder_clause 同语义）。"""
    clauses: list[str] = []
    for f in folders:
        if not f["system"]:
            clauses.append(f"e.folder_id = {params.add(f['id'])}")
        elif f["category"]:
            clauses.append(f"(e.kind = {params.add(f['kind'])} "
                           f"AND e.category = {params.add(f['category'])})")
        else:
            clauses.append(f"e.kind = {params.add(f['kind'])}")
    return " OR ".join(clauses) if clauses else "TRUE"


async def search_entries(
    pool: asyncpg.Pool, query: str, *, folder_ids: list[int] | None = None,
    project_id: int | None = None, kinds: list[str] | None = None,
    content_type: str | None = None, top_k: int = 8,
) -> list[dict[str, Any]]:
    """三级融合检索。返回字段与 kb.search 工具对齐，另带 score/source_name/chunk_seq
    供前端引用回溯。向量路缺席（无 pgvector / 嵌入失败）自动只剩 trgm。"""
    query = (query or "").strip()
    if not query:
        return []
    top_k = max(1, min(int(top_k or 8), 20))

    async with pool.acquire() as conn:
        if folder_ids:
            folders = await conn.fetch(
                "SELECT id,name,title,kind,category,system FROM kb_folders "
                "WHERE id = ANY($1::bigint[])", list(folder_ids))
        else:
            folders = []

        # 参数全动态：每个值用一次 Params.add 生成占位符，子句内可重复引用同一占位符；
        # 不预留"固定位置"，避免任何参数在某条 SQL 里未被引用（asyncpg 报类型不可推断）
        p = Params()
        pid = p.add(project_id)
        ct = p.add(content_type)
        folder_clause = folder_where(folders, p)
        kinds_clause = "TRUE"
        if kinds:
            kinds_clause = f"e.kind = ANY({p.add(list(kinds))}::text[])"
        scope_clause = (f"(e.scope='global' OR ({pid}::bigint IS NOT NULL "
                        f"AND e.project_id={pid}))")
        tag_clause = (f"({ct}::text IS NULL OR cardinality(e.tags)=0 "
                      f"OR {ct} = ANY(e.tags))")
        limit_p = p.add(top_k)  # 最后追加，两条查询共用同一 LIMIT 占位符

        # 向量路：列存在 + 嵌入服务可用才走
        vec_hits: list[dict[str, Any]] = []
        if await _embed_col_exists(conn):
            try:
                vec = await embeddings.embed_one(query)
                if vec:
                    vec_placeholder = f"{p.add(_to_pgvector(vec))}::vector"
                    rows = await conn.fetch(
                        f"""
                        SELECT e.id, e.name, e.title, e.description, e.category, e.kind,
                               e.source_name, e.source_hash, e.chunk_seq,
                               left(e.content, 1200) AS content,
                               1 - (e.embedding <=> {vec_placeholder}) AS sim
                        FROM kb_entries e
                        WHERE e.enabled AND e.embedding IS NOT NULL
                          AND {scope_clause}
                          AND ({folder_clause})
                          AND {tag_clause}
                          AND {kinds_clause}
                        ORDER BY e.embedding <=> {vec_placeholder}
                        LIMIT {limit_p}
                        """,
                        *p.values)
                    vec_hits = [dict(r) for r in rows]
            except Exception:  # noqa: BLE001 — 向量路失败降级 trgm，绝不阻断
                vec_hits = []

        # trgm 路：查询按空白切词（中文整句不切但照样可用），任一词命中即召回；
        # 多词取各词最大相似度。中文环境下 trgm 相似度常为 0（ctype=C），
        # 因此 ILIKE 词匹配是兜底主路，保证关键词检索永不空手而归
        terms = [query] + [t for t in re.split(r"\s+", query) if t][:8]
        match_parts, sim_parts = [], []
        for t in terms:
            tp = p.add(t)
            match_parts.append(
                f"(e.name ILIKE '%'||{tp}||'%' OR e.description ILIKE '%'||{tp}||'%' "
                f"OR e.content ILIKE '%'||{tp}||'%' "
                f"OR similarity(coalesce(e.title, e.name) || ' ' || e.content, {tp}) > 0.10)")
            sim_parts.append(
                f"GREATEST(similarity(coalesce(e.title, e.name), {tp}), "
                f"similarity(e.description, {tp}), similarity(e.content, {tp}))")
        match_clause = "(" + " OR ".join(match_parts) + ")" if match_parts else "TRUE"
        sim_expr = "GREATEST(" + ",".join(sim_parts) + ")" if sim_parts else "0"
        trgm_rows = await conn.fetch(
            f"""
            SELECT e.id, e.name, e.title, e.description, e.category, e.kind,
                   e.source_name, e.source_hash, e.chunk_seq,
                   left(e.content, 1200) AS content,
                   {sim_expr} AS sim
            FROM kb_entries e
            WHERE e.enabled
              AND {scope_clause}
              AND {tag_clause}
              AND ({folder_clause})
              AND {kinds_clause}
              AND {match_clause}
            ORDER BY sim DESC, e.weight DESC, e.id
            LIMIT {limit_p}
            """,
            *p.values)
        trgm_hits = [dict(r) for r in trgm_rows]

    return fuse_scores(vec_hits, trgm_hits, top_k)
