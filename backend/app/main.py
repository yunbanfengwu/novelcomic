"""novelcomic 后端入口：lifespan 拼装（连接池+schema+知识seed+worker）。"""
import asyncio
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, models_registry, resource_map
from .api.admin import router as admin_router
from .api.app_config import router as app_config_router
from .api.case_library import router as case_library_router
from .api.chat import router as chat_router
from .api.character_library import router as character_library_router
from .api.kb_doc import router as kb_doc_router
from .api.kb_extract_staging import router as kb_extract_staging_router
from .api.kb_library import router as kb_library_router
from .api.plans import router as plans_router
from .api.skill_run import router as skill_run_router
from .api.teams import router as teams_router
from .api.usage import router as usage_router
from .api.projects import router as projects_router
from .api.references import router as references_router
from .api.shot_trash import router as shot_trash_router
from .api.shots import router as shots_router
from .api.tags import router as tags_router
from .api.agents import router as agents_router
from .api.tools import router as tools_router
from .api.users import router as users_router
from .api.workflows import router as workflows_router
from .api.assets import router as assets_router
from .api.model_caps import router as model_caps_router
from .knowledge_seed import seed_knowledge
from .knowledge_seed_cocc import seed_cocc_knowledge
# agent_plan / capabilities：import 即把 agent.plan、capability.* 注册进 workflow_actions。
# 注册表另有惰性触发兜底（workflow_actions._ensure_loaded），这里显式 import 是让
# 「进程起来 = 动作齐全」成为确定事实，不依赖谁先调了 specs()。
from .services import agent_plan, capabilities  # noqa: F401
from .services import workflow as workflow_service
from .services.worker import worker_loop

# 日志双写：控制台 + backend/logs/backend.log（utf-8，10MB×3 轮转）——
# 排查"生成到底提交了什么"时可离线翻文件，不依赖开着的控制台
_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(_LOG_DIR / "backend.log", maxBytes=10_000_000,
                            backupCount=3, encoding="utf-8"),
    ],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await db.init_pool()
    n = await seed_knowledge(pool)
    n2 = await seed_cocc_knowledge(pool)
    if n or n2:
        logging.info("公共知识 seed %d 条 + cocc-work 迁移 %d 条", n, n2)
    n3 = await models_registry.seed_profiles()
    if n3:
        logging.info("模型注册表 seed %d 档", n3)
    n4 = await resource_map.seed_if_empty(pool)
    if n4:
        logging.info("资源包剩余 seed %d 条", n4)
    # 工作流运行对账：重启把在跑的 run 标 failed（子任务不受影响，见 reconcile_runs）
    n5 = await workflow_service.reconcile_runs(pool)
    if n5:
        logging.info("workflow 对账：%d 个中断 run 标 failed", n5)
    stop = asyncio.Event()
    worker = asyncio.create_task(worker_loop(pool, stop))
    yield
    stop.set()
    await worker
    await db.close_pool()


app = FastAPI(title="novelcomic", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5175", "http://127.0.0.1:5175",  # 5175=Claude 预览验证实例
                   "null"],  # file:// 直接打开的本地静态页（如 cankao_knowledge.html 手动上传用）
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)
app.include_router(references_router)
app.include_router(shots_router)
app.include_router(shot_trash_router)
app.include_router(admin_router)
app.include_router(kb_library_router)
app.include_router(kb_extract_staging_router)
app.include_router(case_library_router)
app.include_router(chat_router)
app.include_router(character_library_router)
app.include_router(app_config_router)
app.include_router(tags_router)
# 工作流引擎（2026-07-29）：纯新增入口，不改任何既有链路行为
app.include_router(workflows_router)
app.include_router(assets_router)
# 模型能力档案（2026-09-17）：画布/生成条按档案自适应的数据源（公开只读）
app.include_router(model_caps_router)
# 工具 + 用户（2026-07-29）：技能调用的统一入口 / 数据归属地基，同样是纯新增
app.include_router(tools_router)
app.include_router(agents_router)
app.include_router(users_router)
# 平台补强（2026-09-17 P1-P5）：文档摄取检索 / 技能试运行与用量 / 规划落库 /
# token 计量 / 团队与分享——全部纯新增 router，不动既有链路
app.include_router(kb_doc_router)
app.include_router(skill_run_router)
app.include_router(plans_router)
app.include_router(usage_router)
app.include_router(teams_router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
