"""P1 知识库补强测试：文档摄取（解析/分块/幂等）与混合检索融合（2026-09-17）。

纯单元：分块/解析/融合排序是纯函数直接测；ingest 的落库路径用假 pool 测
「嵌入缺席时降级为纯文本块、同 hash 重建先删后插」两条契约。
"""
import asyncio
import io
import zipfile
from unittest.mock import patch

from backend.app.services import kb_ingest


# ── 分块器 ────────────────────────────────────────────────────────────────

def test_chunk_text_empty_and_short():
    assert kb_ingest.chunk_text("") == []
    assert kb_ingest.chunk_text("   \n  \r\n ") == []
    one = kb_ingest.chunk_text("短文本一段。")
    assert len(one) == 1 and one[0] == "短文本一段。"


def test_chunk_text_respects_max_chars_hard_limit():
    text = "这是一个很长的句子。" * 300  # 无换行的超长段
    blocks = kb_ingest.chunk_text(text, max_chars=300, overlap=0)
    assert blocks, "超长段必须切出块"
    assert all(len(b) <= 300 for b in blocks), "块长是硬上限"


def test_chunk_text_markdown_heading_forces_new_block():
    text = "第一段内容。\n## 新章节标题\n第二段内容。"
    blocks = kb_ingest.chunk_text(text, max_chars=800, overlap=0)
    assert len(blocks) == 2
    assert blocks[1].startswith("## 新章节标题")


def test_chunk_text_overlap_carries_previous_tail():
    text = "\n".join(f"段落{i}：" + "内容" * 200 for i in range(3))
    blocks = kb_ingest.chunk_text(text, max_chars=200, overlap=40)
    assert len(blocks) > 1
    for prev, cur in zip(blocks, blocks[1:]):
        assert cur.startswith(prev[-40:])


def test_source_fingerprint_stable_and_sensitive():
    a = kb_ingest.source_fingerprint("hello")
    b = kb_ingest.source_fingerprint("hello ")
    assert a == kb_ingest.source_fingerprint("hello") and a != b


# ── 解析器 ────────────────────────────────────────────────────────────────

def _make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        "<w:p>" + "".join(f"<w:t>{p}</w:t>" for p in para.split("|")) + "</w:p>"
        for para in paragraphs)
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
           + body + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_parse_docx_paragraphs_and_escapes():
    data = _make_docx(["第一段&lt;A&gt;", "第二段&amp;更多"])
    text = kb_ingest.parse_docx(data)
    assert "第一段<A>" in text and "第二段&更多" in text
    assert "\n" in text  # 段落边界保留


def test_parse_docx_invalid_raises_valueerror():
    import pytest
    with pytest.raises(ValueError):
        kb_ingest.parse_docx(b"not a zip")


def test_parse_document_dispatch_and_encoding_fallback():
    assert kb_ingest.parse_document("a.txt", "gbk文本".encode("gbk")) == "gbk文本"
    assert "indent" not in kb_ingest.parse_document("a.md", "# 标题\n正文".encode())
    obj = kb_ingest.parse_document("a.json", b'[{"k":"v"}]')
    assert '"k"' in obj  # JSON 还原成可读缩进文本
    assert kb_ingest.parse_document("x.html", b"<p>A</p><p>B</p>").split() == ["A", "B"]


# ── 检索融合（纯函数）────────────────────────────────────────────────────

def test_fuse_scores_weights_and_dedup():
    vec = [{"id": 1, "sim": 1.0, "chunk_seq": 0}, {"id": 2, "sim": 0.5, "chunk_seq": 1}]
    trgm = [{"id": 1, "sim": 0.5, "chunk_seq": 0}, {"id": 3, "sim": 0.8, "chunk_seq": 2}]
    out = kb_ingest.fuse_scores(vec, trgm, top_k=3)
    scores = {r["id"]: r["score"] for r in out}
    # id=1 双路命中：0.6*1.0 + 0.4*0.8? 不——trgm 只取 0.4 权重：0.6*1 + 0.4*0.5 = 0.8
    assert abs(scores[1] - 0.8) < 1e-6
    # id=2 只有向量路：0.6*0.5=0.3；id=3 只有 trgm 路：0.4*0.8=0.32 → 3 排在 2 前
    assert out[1]["id"] == 3 and out[2]["id"] == 2


def test_fuse_scores_topk_and_tiebreak_by_chunk_seq():
    hits = [{"id": i, "sim": 0.5, "chunk_seq": 10 - i} for i in range(1, 6)]
    out = kb_ingest.fuse_scores([], hits, top_k=3)
    assert len(out) == 3
    # 同分时 chunk_seq 小者在前（文档顺序）
    assert [r["chunk_seq"] for r in out] == sorted(r["chunk_seq"] for r in out)


def test_folder_where_system_vs_custom():
    # folder_where 只吃鸭子类型（id/kind/category/system），不依赖 asyncpg.Record
    sys_folder = {"id": 7, "kind": "knowledge", "category": None, "system": True}
    custom = {"id": 9, "kind": None, "category": None, "system": False}
    p = kb_ingest.Params()
    clause = kb_ingest.folder_where([sys_folder, custom], p)
    assert clause == "e.kind = $1 OR e.folder_id = $2"
    assert p.values == ["knowledge", 9]  # 自定义文件夹按自身 id 归属


# ── 摄取落库（假 pool：降级与幂等两条契约）────────────────────────────────

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, state):
        self.state = state

    def transaction(self):
        return _FakeTx()

    async def fetchval(self, sql, *args):
        # _embed_col_exists 的探测查询：返回 None（无 pgvector）
        if "information_schema.columns" in sql:
            return None
        raise AssertionError(f"unexpected fetchval: {sql[:60]}")

    async def execute(self, sql, *args):
        if sql.lstrip().upper().startswith("DELETE"):
            self.state["deleted"] += 1
            self.state["delete_args"] = args
        return "OK"

    async def fetchrow(self, sql, *args):
        assert "embedding" not in sql, "无 pgvector 时插入语句不得携带向量列"
        self.state["inserted"] += 1
        return {"id": self.state["inserted"]}


class _FakePool:
    def __init__(self, state):
        self.state = state

    def acquire(self):
        state = self.state

        class _C:
            async def __aenter__(self_inner):
                return _FakeConn(state)

            async def __aexit__(self, *exc):
                return False

        return _C()


def test_ingest_degrades_without_pgvector_and_rebuilds_by_hash():
    state = {"deleted": 0, "inserted": 0, "delete_args": None}
    pool = _FakePool(state)
    text = "第一章 开端\n" + "正文内容。" * 300
    with patch("backend.app.services.kb_ingest.embeddings.embed",
               side_effect=RuntimeError("no embedding service")):
        out = asyncio.run(kb_ingest.ingest_document(
            pool, title="测试文档", text=text, scope="project", project_id=42))
    assert out["chunks"] > 0
    assert out["embedded"] == 0 and out["entry_ids"] == list(range(1, out["chunks"] + 1))
    assert state["deleted"] == 1 and state["delete_args"][0] == out["source_hash"]

    # 同文档重复摄取：hash 一致 → 幂等重建路径
    with patch("backend.app.services.kb_ingest.embeddings.embed",
               side_effect=RuntimeError("no embedding service")):
        out2 = asyncio.run(kb_ingest.ingest_document(
            pool, title="测试文档", text=text, scope="project", project_id=42))
    assert out2["source_hash"] == out["source_hash"]


def test_ingest_project_scope_requires_project_id():
    import pytest
    with pytest.raises(ValueError):
        asyncio.run(kb_ingest.ingest_document(
            _FakePool({"deleted": 0, "inserted": 0}), title="t", text="x",
            scope="project", project_id=None))
