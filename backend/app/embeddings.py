"""向量嵌入客户端：OpenAI 兼容 /embeddings（按 purpose='embedding' 取 active 档，兜底 LLM 档）。

维度锁定 1024（BAAI/bge-m3）。库侧 kb_entries.embedding 为 vector(1024)，务必与此一致。
"""
import httpx

from . import models_registry
from .settings import settings

EMBED_DIM = 1024  # BAAI/bge-m3；换模型改维度须同步改 14_vector.sql 的 vector(N)

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


async def _profile() -> tuple[str, str, str]:
    """(base_url, api_key, model) —— embedding 档；未配则回落 LLM 档（同为硅基流动）。"""
    try:
        p = await models_registry.get_active("embedding")
    except Exception:  # noqa: BLE001 — 表未建/池未起时兜底 env
        p = None
    if p and p["api_key"]:
        return p["base_url"].rstrip("/"), p["api_key"], p["model_name"]
    # 兜底：复用 LLM（硅基流动）凭据 + 默认 bge-m3
    return settings.LLM_BASE_URL.rstrip("/"), settings.LLM_API_KEY, "BAAI/bge-m3"


async def embed(texts: list[str]) -> list[list[float]]:
    """批量把文本转成向量。空输入返回 []；单条超长由提供商截断。

    返回顺序与入参一致，每个向量维度 = EMBED_DIM(1024)。
    """
    texts = [t if t else " " for t in texts]  # 空串会被拒，占位
    if not texts:
        return []
    base, key, model = await _profile()
    if not key:
        raise RuntimeError("未配置 embedding/LLM 的 api_key，无法生成向量")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if "doubao-embedding-vision" in model.lower() and "/api/coding/v3" not in base:
            # 方舟多模态 API 每种 input type 最多一个，文本批次需逐条请求。
            endpoint = (base if base.endswith("/embeddings/multimodal")
                        else f"{base}/embeddings/multimodal")
            out: list[list[float]] = []
            for text in texts:
                r = await client.post(
                    endpoint, headers=headers,
                    json={"model": model, "input": [{"type": "text", "text": text}],
                          "encoding_format": "float"},
                )
                r.raise_for_status()
                data = r.json().get("data")
                item = data[0] if isinstance(data, list) else data
                vector = item.get("embedding") if isinstance(item, dict) else None
                while isinstance(vector, list) and len(vector) == 1 and isinstance(vector[0], list):
                    vector = vector[0]
                if not isinstance(vector, list):
                    raise RuntimeError("方舟多模态向量响应缺少 embedding")
                out.append(vector)
            return out
        body = {"model": model, "input": texts, "encoding_format": "float"}
        if "Qwen3-Embedding" in model:
            body["dimensions"] = EMBED_DIM
        endpoint = base if base.endswith("/embeddings") else f"{base}/embeddings"
        r = await client.post(endpoint, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]


async def embed_one(text: str) -> list[float]:
    """单条便捷封装。"""
    vecs = await embed([text])
    return vecs[0] if vecs else []


def to_pgvector(vec: list[float]) -> str:
    """把 float 列表格式化成 pgvector 字面量 '[0.1,0.2,...]'，用于 SQL 参数。"""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
