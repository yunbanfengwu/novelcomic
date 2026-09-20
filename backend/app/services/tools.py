"""工具清单：把系统能力做成「技能/工作流/管理台都能调用」的统一入口。

为什么**查询不逐个封装成小工具**：
后端现有 53 个 GET 端点，手写 53 个包装意味着每加一个筛选条件就要改两处，
迟早与端点漂移（workflow_actions 模块头记的就是这个教训）。而查询本来就没有装配
逻辑——它就是 SQL。所以查询给一把 `db.query`（只读）+ 一把 `db.schema`（自解释），
一次覆盖全部组合，且永远不会过期。

为什么**写不给裸 SQL**：
1) 外键大面积 ON DELETE CASCADE，一条 DELETE 能顺带清掉整条产物链，没有回滚；
2) 关键状态都塞在 JSONB 里（content_elements.meta 就有 sheet_url / extra_refs /
   sheet_ref_off / variants 等约定字段），一条 `SET meta='{...}'` 就把同级字段整块抹掉；
3) 真正的装配逻辑在端点/Step 里，不在 SQL 里，绕过它写库只会写出半成品数据。
所以写一律走命名动作（workflow_actions 注册表），一个动作 = 一段与端点同源的薄封装。

安全边界（db.query）：单条语句 + 必须 SELECT/WITH 开头 + 只读事务（Postgres 层兜底，
正则拦不住的也写不进去）+ statement_timeout + 游标限行 + 全量落 tool_calls 审计。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import asyncpg

from . import workflow_actions

QUERY_TIMEOUT_MS = 15_000
DEFAULT_LIMIT = 200
MAX_LIMIT = 2000

# 只读 SQL 的两道正则闸：入口必须是 SELECT/WITH，且不得出现写语句关键字
# （`WITH t AS (DELETE … RETURNING *) SELECT …` 这种数据修改 CTE 就是靠第二道拦的）。
_HEAD_OK = re.compile(r"^\s*(select|with)\b", re.I)
_WRITE_WORD = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|"
    r"reindex|refresh|call|lock|listen|notify|prepare|execute|do|set|reset|"
    r"pg_sleep|pg_read_file|pg_ls_dir|dblink)\b", re.I)
_STRING_LIT = re.compile(r"'(?:[^']|'')*'")
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


class ToolError(Exception):
    """工具调用被拒绝或执行失败（对调用方是可预期的错误，不是 500）。"""


def check_read_only_sql(sql: str) -> str:
    """校验并归一化一条只读 SQL；不通过就抛 ToolError（带明确原因，方便模型自我修正）。"""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise ToolError("sql 不能为空")
    # 先摘掉注释和字符串字面量再查关键字，否则 WHERE kind='update' 这种会被误伤
    bare = _STRING_LIT.sub("''", _COMMENT.sub(" ", text))
    if ";" in bare:
        raise ToolError("只允许单条语句（检测到分号）")
    if not _HEAD_OK.match(bare):
        raise ToolError("只允许只读查询：语句须以 SELECT 或 WITH 开头")
    hit = _WRITE_WORD.search(bare)
    if hit:
        raise ToolError(f"只读工具不允许出现 {hit.group(0).upper()}；增删改请用对应的命名动作工具")
    return text


async def db_query(pool: asyncpg.Pool, *, sql: str, args: list[Any] | None = None,
                   limit: int = DEFAULT_LIMIT, **_: Any) -> dict[str, Any]:
    """执行一条只读 SQL。参数用 $1/$2 占位符传 args，别拼字符串。"""
    text = check_read_only_sql(sql)
    n = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            # 只读事务是真正的兜底：正则漏掉的写语句到这里由 Postgres 直接拒绝
            await conn.execute(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}")
            try:
                cur = await conn.cursor(text, *(args or []))
                rows = await cur.fetch(n)
                more = bool(await cur.fetch(1))
            except asyncpg.PostgresError as e:
                raise ToolError(f"SQL 执行失败：{e}") from e
    cols = list(rows[0].keys()) if rows else []
    return {"columns": cols, "rows": [dict(r) for r in rows],
            "row_count": len(rows), "truncated": more}


async def db_schema(pool: asyncpg.Pool, *, table: str | None = None,
                    **_: Any) -> dict[str, Any]:
    """库结构说明书。不传 table = 表清单+表注释；传 table = 该表的列/类型/注释。

    这库的 COMMENT 写得很全（分镜 meta 的字段约定都在注释里），所以本工具就是
    db.query 的配套文档——先 schema 后 query，模型不用猜列名。
    """
    if not table:
        rows = await pool.fetch(
            "SELECT c.relname AS table, obj_description(c.oid) AS comment, "
            "       c.reltuples::bigint AS approx_rows "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname")
        return {"tables": [dict(r) for r in rows]}

    rows = await pool.fetch(
        "SELECT a.attname AS column, format_type(a.atttypid, a.atttypmod) AS type, "
        "       NOT a.attnotnull AS nullable, "
        "       pg_get_expr(d.adbin, d.adrelid) AS default, "
        "       col_description(c.oid, a.attnum) AS comment "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped "
        "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
        "WHERE n.nspname = 'public' AND c.relname = $1 ORDER BY a.attnum", table)
    if not rows:
        raise ToolError(f"表 {table!r} 不存在")
    comment = await pool.fetchval(
        "SELECT obj_description(to_regclass('public.' || $1))", table)
    return {"table": table, "comment": comment, "columns": [dict(r) for r in rows]}


# 内置工具：不属于任何业务域，直接在这里定义（业务工具一律走 workflow_actions 注册表）
_BUILTIN: dict[str, dict[str, Any]] = {
    "db.schema": {
        "name": "db.schema", "title": "查看库结构", "writes": False,
        "description": db_schema.__doc__.strip(),
        "params": {"table": {"type": "string", "required": False,
                             "desc": "表名；留空返回全部表清单"}},
        "outputs": {"tables": {"type": "array", "desc": "表清单（未指定 table 时）"},
                    "columns": {"type": "array", "desc": "字段清单（指定 table 时）"}},
        "fn": db_schema,
    },
    "db.query": {
        "name": "db.query", "title": "只读 SQL 查询", "writes": False,
        "description": "执行一条只读 SQL（单条语句、SELECT/WITH 开头、只读事务、"
                       f"{QUERY_TIMEOUT_MS // 1000}s 超时、最多返回 {MAX_LIMIT} 行）。"
                       "JSONB 列取回来是 JSON 字符串，取标量建议直接写 meta->>'字段'。",
        "params": {
            "sql": {"type": "string", "required": True, "desc": "SELECT 语句，占位符用 $1/$2"},
            "args": {"type": "array", "required": False, "desc": "占位符实参，按顺序"},
            "limit": {"type": "int", "required": False,
                      "desc": f"最多返回行数，默认 {DEFAULT_LIMIT}"},
        },
        "outputs": {
            "columns": {"type": "array", "desc": "返回列名"},
            "rows": {"type": "array", "desc": "查询结果行"},
            "row_count": {"type": "int", "desc": "返回行数"},
            "truncated": {"type": "bool", "desc": "是否因上限截断"},
        },
        "fn": db_query,
    },
}


def specs() -> list[dict[str, Any]]:
    """工具清单（给管理台渲染、给技能做 tool schema）。"""
    out = [{k: v for k, v in t.items() if k != "fn"} for t in _BUILTIN.values()]
    out += [{**s, "group": s["name"].split(".")[0]} for s in workflow_actions.specs()]
    for t in out:
        t.setdefault("group", t["name"].split(".")[0])
        t.setdefault("params", {})
        t.setdefault("outputs", {})
    return sorted(out, key=lambda t: (t["group"], t["name"]))


def _resolve(name: str):
    if name in _BUILTIN:
        return _BUILTIN[name]["fn"], _BUILTIN[name]
    fn = workflow_actions.get(name)
    if fn:
        return fn, (workflow_actions.spec(name) or {"name": name, "writes": False})
    raise ToolError(f"未知工具 {name!r}")


async def invoke(pool: asyncpg.Pool, name: str, args: dict[str, Any], *,
                 caller: str = "sys_dev", source: str = "admin_ui",
                 project_id: int | None = None,
                 flow_ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用一个工具并落审计。工具自己抛的 ToolError 会原样带出去（附带审计已落）。

    flow_ctx 只在工具声明了 `wants_ctx` 时透传为 `_ctx`——**不进 args、不进审计**：
    它是内存态运行上下文（整份 ctx，含各上游节点产出），塞进 tool_calls.args 等于
    把每次调用的全量上下文抄一份进审计表，既没用也会撑爆。
    """
    fn, spec = _resolve(name)
    missing = [k for k, p in (spec.get("params") or {}).items()
               if p.get("required") and args.get(k) in (None, "")]
    if missing:
        raise ToolError(f"缺少必填参数：{', '.join(missing)}")
    extra = {"_ctx": flow_ctx} if (spec.get("wants_ctx") and flow_ctx is not None) else {}

    t0 = time.monotonic()
    ok, err, result, rows = True, None, None, None
    try:
        result = await fn(pool, **args, **extra)
        rows = result.get("row_count") if isinstance(result, dict) else None
    except ToolError as e:
        ok, err = False, str(e)
        raise
    except Exception as e:  # noqa: BLE001 — 审计要记下所有失败，记完再原样抛
        ok, err = False, f"{type(e).__name__}: {e}"
        raise
    finally:
        try:
            await pool.execute(
                "INSERT INTO tool_calls(tool,caller,source,project_id,args,ok,row_count,"
                "error,duration_ms) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9)",
                name, caller, source, project_id,
                json.dumps(args, ensure_ascii=False, default=str), ok, rows, err,
                int((time.monotonic() - t0) * 1000))
        except Exception:  # noqa: BLE001 — 审计写失败不能反过来把业务调用弄挂
            pass
    return result
