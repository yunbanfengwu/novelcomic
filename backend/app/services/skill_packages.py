"""Agent Skills 规范能力包：安装、校验、资源文件与员工挂载。"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TEXT_EXT = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts",
             ".sh", ".ps1", ".html", ".css", ".csv", ".toml"}


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        raise ValueError("SKILL.md 必须以 YAML frontmatter 开头")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("SKILL.md frontmatter 未闭合")
    out: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip().strip("\"'")
    name, desc = out.get("name", ""), out.get("description", "")
    if not _SLUG.fullmatch(name):
        raise ValueError("Skill name 必须使用小写字母、数字和连字符")
    if not desc:
        raise ValueError("Skill description 必填，且应说明能力与触发时机")
    return out


def _tags(meta: dict[str, str]) -> list[str]:
    """Read optional content-type tags from SKILL.md frontmatter."""
    raw = meta.get("tags") or meta.get("content_types") or ""
    return [x.strip() for x in re.split(r"[,，\s]+", raw) if x.strip()]


async def _download(source_url: str) -> tuple[str, dict[str, str]]:
    """返回 SKILL.md 与包内文本资源。支持 GitHub repo/tree 和直接 SKILL.md URL。"""
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("只允许 http/https Skill 来源")
    timeout = httpx.Timeout(60, connect=15)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        if parsed.netloc.lower() == "github.com":
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) < 2:
                raise ValueError("GitHub 地址必须包含 owner/repo")
            owner, repo = parts[0], parts[1].removesuffix(".git")
            branch, subpath = "main", ""
            if len(parts) >= 4 and parts[2] == "tree":
                branch = parts[3]
                subpath = "/".join(parts[4:]).strip("/")
            response = await client.get(
                f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}")
            if response.status_code == 404 and branch == "main":
                response = await client.get(
                    f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master")
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
                candidates = [
                    n for n in names
                    if n.endswith("/SKILL.md")
                    and (not subpath or f"/{subpath}/SKILL.md" in f"/{n}")
                ]
                if not candidates:
                    raise ValueError("GitHub 包内没有找到 SKILL.md")
                skill_path = min(candidates, key=len)
                root = skill_path[:-len("SKILL.md")]
                files: dict[str, str] = {}
                for name in names:
                    if not name.startswith(root):
                        continue
                    rel = name[len(root):]
                    if not rel or ".." in rel.split("/") or archive.getinfo(name).file_size > 1_000_000:
                        continue
                    suffix = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
                    if suffix in _TEXT_EXT or rel == "SKILL.md":
                        files[rel] = archive.read(name).decode("utf-8", errors="replace")
                return files["SKILL.md"], files
        response = await client.get(source_url)
        response.raise_for_status()
        text = response.text
        return text, {"SKILL.md": text}


async def install(pool: asyncpg.Pool, source_url: str) -> dict[str, Any]:
    skill_md, files = await _download(source_url)
    meta = _frontmatter(skill_md)
    manifest = {
        "format": "agentskills.io", "source": source_url,
        "files": sorted(files), "progressive_disclosure": True,
    }
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "INSERT INTO skill_packages(slug,name,description,version,source_url,license,tags,"
            "skill_md,manifest,status) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,'installed') "
            "ON CONFLICT(slug) DO UPDATE SET name=excluded.name,description=excluded.description,"
            "version=excluded.version,source_url=excluded.source_url,license=excluded.license,"
            "skill_md=excluded.skill_md,manifest=excluded.manifest,tags=excluded.tags,"
            "status='installed',updated_at=now() "
            "RETURNING *",
            meta["name"], meta.get("title") or meta["name"], meta["description"],
            meta.get("version", "0.1.0"), source_url, meta.get("license"),
            _tags(meta), skill_md, json.dumps(manifest, ensure_ascii=False))
        await conn.execute("DELETE FROM skill_package_files WHERE skill_id=$1", row["id"])
        for path, content in files.items():
            await conn.execute(
                "INSERT INTO skill_package_files(skill_id,path,content,sha256) VALUES($1,$2,$3,$4)",
                row["id"], path, content,
                hashlib.sha256(content.encode("utf-8")).hexdigest())
    return {**dict(row), "manifest": manifest}


async def list_packages(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT s.*,coalesce((SELECT count(*) FROM agent_template_skills b "
        "WHERE b.skill_id=s.id AND b.enabled),0) AS agent_count,"
        "coalesce((SELECT count(*) FROM skill_package_files f WHERE f.skill_id=s.id),0) AS file_count "
        "FROM skill_packages s ORDER BY s.updated_at DESC")
    return [{**dict(r), "manifest": r["manifest"] if isinstance(r["manifest"], dict)
             else json.loads(r["manifest"] or "{}")} for r in rows]


async def list_agents(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT t.*,coalesce(jsonb_agg(jsonb_build_object('id',s.id,'slug',s.slug,'name',s.name) "
        "ORDER BY s.name) FILTER(WHERE s.id IS NOT NULL),'[]'::jsonb) AS skills "
        "FROM agent_templates t LEFT JOIN agent_template_skills b "
        "ON b.agent_template_id=t.id AND b.enabled "
        "LEFT JOIN skill_packages s ON s.id=b.skill_id GROUP BY t.id ORDER BY t.name")
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, fallback in (("skills", []), ("config", {})):
            value = item.get(key)
            if isinstance(value, str):
                try:
                    item[key] = json.loads(value)
                except json.JSONDecodeError:
                    item[key] = fallback
            elif value is None:
                item[key] = fallback
        out.append(item)
    return out


async def set_agent_skills(
    pool: asyncpg.Pool, agent_template_id: int, skill_ids: list[int],
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        if not await conn.fetchval("SELECT 1 FROM agent_templates WHERE id=$1", agent_template_id):
            raise ValueError("数字员工不存在")
        await conn.execute(
            "DELETE FROM agent_template_skills WHERE agent_template_id=$1", agent_template_id)
        for skill_id in dict.fromkeys(skill_ids):
            await conn.execute(
                "INSERT INTO agent_template_skills(agent_template_id,skill_id) VALUES($1,$2)",
                agent_template_id, skill_id)
        # 同步同 code 的现有项目员工；只补模板绑定，不删除项目的额外挂载。
        await conn.execute(
            "INSERT INTO agent_skill_bindings(agent_id,skill_id) "
            "SELECT a.id,b.skill_id FROM agents a JOIN agent_templates t ON t.code=a.code "
            "JOIN agent_template_skills b ON b.agent_template_id=t.id "
            "WHERE t.id=$1 ON CONFLICT DO NOTHING", agent_template_id)
