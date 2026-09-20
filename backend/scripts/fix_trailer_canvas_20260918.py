"""一次性修正：先导预告片画布（模板 + 项目26实例）
1. 删除「蒸馏预告片提示词」（trailer.distill 工具）节点及其连线；
2. 「生成预告片」节点 modality 修正为 video（曾被保存链路覆写成 image）；
3. 生成节点 payload 不再引用 {{distill.*}}——提示词为空时由 TrailerStep 自动蒸馏兜底，
   生成条手写（node_overrides.prompt）仍优先生效。
"""
import asyncio
import json
import sys

import asyncpg

SLUGS = [
    "project-trailer-canvas",                              # 模板
    "project-trailer-canvas@project-26@project-trailer",   # 项目26 实例
]
DSN = "postgresql://postgres:123456@localhost:5432/novelcomic"


def fix_graph(graph: dict) -> tuple[dict, list[str]]:
    notes: list[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    def cfg(n: dict) -> dict:
        c = n.get("config")
        if isinstance(c, str):
            c = json.loads(c or "{}")
        return c if isinstance(c, dict) else {}

    # 1) 找出蒸馏节点（action + name=trailer.distill）并剔除
    distill_ids = {n.get("id") for n in nodes
                   if cfg(n).get("name") == "trailer.distill"
                   or cfg(n).get("step") == "trailer.distill"}
    if distill_ids:
        ups = [e for e in edges if e.get("to") in distill_ids
               and e.get("from") not in distill_ids]
        nodes = [n for n in nodes if n.get("id") not in distill_ids]
        edges = [e for e in edges
                 if e.get("from") not in distill_ids and e.get("to") not in distill_ids]
        notes.append(f"removed distill nodes: {sorted(distill_ids)}")
        # 蒸馏节点的上游改接到下游 gen：链不断（start→gen）
        gen_id = next((n.get("id") for n in nodes if n.get("type") == "gen"
                       and cfg(n).get("step") == "gen_trailer"), None)
        if gen_id:
            for e in ups:
                if e.get("from") != gen_id:
                    edges.append({**e, "to": gen_id})
                    notes.append(f"rewired {e['from']}->{gen_id}")

    # 2) gen 节点：modality=video；payload 里的 distill 引用清掉
    for n in nodes:
        c = cfg(n)
        if n.get("type") == "gen":
            c["modality"] = "video"
            pay = c.get("payload")
            if isinstance(pay, str):
                pay = json.loads(pay or "{}")
            pay = pay if isinstance(pay, dict) else {}
            for k in list(pay):
                v = pay[k]
                if isinstance(v, str) and "distill." in v:
                    pay.pop(k)
                    notes.append(f"payload.{k} dropped (was {v!r})")
            c["payload"] = pay
            n["config"] = c
            notes.append(f"gen node {n.get('id')}: modality=video")

    graph["nodes"], graph["edges"] = nodes, edges
    return graph, notes


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        for slug in SLUGS:
            row = await conn.fetchrow(
                "SELECT id, slug, version, graph FROM workflows WHERE slug=$1 "
                "ORDER BY version DESC LIMIT 1", slug)
            if not row:
                print(f"!! not found: {slug}")
                continue
            graph = row["graph"]
            if isinstance(graph, str):
                graph = json.loads(graph)
            fixed, notes = fix_graph(graph)
            await conn.execute(
                "UPDATE workflows SET graph=$2::jsonb, updated_at=now() WHERE id=$1",
                row["id"], json.dumps(fixed, ensure_ascii=False))
            print(f"== {slug} (v{row['version']})")
            for n in notes:
                print("   -", n)
    finally:
        await conn.close()

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
