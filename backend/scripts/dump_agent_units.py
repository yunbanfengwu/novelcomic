"""导出 workflows 表各智能体编排（每 slug 最新版）的 config 到 docs 快照文档。

用途：编排的 charter/task 只存在数据库、画布上改完仓库里看不见——定期导出快照
让它可 review、可 diff（单一实现原则的配套，见 docs/orchestration-audit-2026-07-31.md §五）。
**只读导出，不写库；快照不是自动执行的 seed，不会冲掉画布手编。**

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe backend/scripts/dump_agent_units.py [DSN]
DSN 缺省用本地开发库。
"""
import asyncio
import datetime
import json
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.agent_unit import merge_config  # noqa: E402

DEFAULT_DSN = "postgresql://postgres:123456@localhost:5432/novelcomic"

FIELDS = ("charter", "task", "skills", "folder_ids", "tools", "tool_names", "args",
          "ref_flows", "ref_each", "dep_mode", "step", "batch", "only_missing",
          "writes", "attach", "notify", "then_flows", "on_fail", "inputs", "params")


async def main() -> None:
    dsn = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DSN
    today = datetime.date.today().isoformat()
    out_path = Path(__file__).resolve().parents[2] / "docs" / f"agent-units-snapshot-{today}.md"
    conn = await asyncpg.connect(dsn)
    rows = await conn.fetch(
        "SELECT DISTINCT ON (slug) slug, version, name, status, seq, graph "
        "FROM workflows ORDER BY slug, version DESC")
    await conn.close()
    units, dags = [], []
    for r in sorted(rows, key=lambda x: (x["seq"] if x["seq"] is not None else 9999, x["slug"])):
        graph = r["graph"] if isinstance(r["graph"], dict) else json.loads(r["graph"] or "{}")
        nodes = graph.get("nodes") or []
        if any(n.get("type") == "unit" for n in nodes):
            units.append((r, merge_config(graph)))
        else:
            dags.append(r)
    lines = [
        f"# 智能体编排 config 快照（{today}，本地库导出）",
        "",
        "> 由 `backend/scripts/dump_agent_units.py` 从 `workflows` 表导出（每 slug 取最新版本），",
        "> 用途：让只存在数据库里的 charter/task 在仓库里可 review、可 diff。",
        "> **这不是自动执行的 seed**——不会在启动时回写，画布上的手编不受影响。",
        "",
    ]
    for r, cfg in units:
        lines.append(f"## {r['slug']} v{r['version']}（{r['name']}，{r['status']}，seq={r['seq']}）")
        lines.append("")
        for k in FIELDS:
            v = cfg.get(k)
            if v in (None, "", [], {}):
                continue
            if isinstance(v, str) and "\n" not in v and len(v) < 100:
                lines.append(f"- **{k}**：{v}")
            elif isinstance(v, str):
                lines.append(f"- **{k}**：")
                lines.append("  ```")
                lines.extend("  " + x for x in v.splitlines())
                lines.append("  ```")
            else:
                lines.append(f"- **{k}**：`{json.dumps(v, ensure_ascii=False)}`")
        lines.append("")
    if dags:
        lines.append("## 工作流引擎 DAG 图（非 unit，仅列名）")
        lines.append("")
        for r in dags:
            lines.append(f"- {r['slug']} v{r['version']}（{r['name']}，{r['status']}）")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"exported {len(units)} units + {len(dags)} dags -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
