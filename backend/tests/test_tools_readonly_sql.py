"""db.query 的只读闸门。

真正兜底的是只读事务（Postgres 层直接拒绝写），但正则这一层要先把话说清楚：
错误信息要能让调用方（尤其是模型）自己改对，而不是丢一个 Postgres 报错。
"""
import pytest

from backend.app.services.tools import ToolError, check_read_only_sql


@pytest.mark.parametrize("sql", [
    "SELECT id, title FROM content_projects",
    "  select 1  ",
    "WITH t AS (SELECT id FROM content_nodes WHERE kind='shot') SELECT count(*) FROM t",
    "SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1",
    "SELECT id FROM content_projects ORDER BY id DESC LIMIT 10;",   # 结尾分号会被吃掉
])
def test_read_only_queries_pass(sql):
    assert check_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "UPDATE content_projects SET title='x' WHERE id=1",
    "DELETE FROM content_nodes WHERE id=1",
    "SELECT 1; DROP TABLE users",
    # 数据修改 CTE：以 WITH 开头，光看句首是拦不住的
    "WITH t AS (DELETE FROM tool_calls RETURNING *) SELECT * FROM t",
    "SELECT pg_sleep(60)",
    "",
])
def test_write_and_multi_statement_rejected(sql):
    with pytest.raises(ToolError):
        check_read_only_sql(sql)


def test_write_keyword_inside_string_literal_is_not_a_write():
    """WHERE status='update' 不是写语句——查关键字前必须先摘掉字符串字面量，
    否则合法查询会被莫名其妙地拒掉。"""
    assert check_read_only_sql("SELECT id FROM content_projects WHERE status='update'")


def test_write_keyword_inside_comment_is_not_a_write():
    assert check_read_only_sql("SELECT id FROM content_projects -- 别 delete 这些行")
