"""同步代码内提示词常量 → kb_entries（生产/本地通用，幂等可重复执行）。

背景：kb_entries 的技能/风格块内容重启不覆盖（管理页是权威版本），代码侧升级
质检规则或风格块后需要手动同步。本脚本同步两类：
  1. 质检规则（首帧/视频提示词质检）
  2. 画风块（category=style）的 content/positive/negative

2026-07-16 精调 7 种画风（Seedream 4.x 指令跟随特性调研沉淀）：
  写实科幻 / 诺兰IMAX / 史诗奇幻 / 新海诚 / 皮克斯 / 电影感写实 / 阿凡达奇观。
  原则：positive 精炼 6-9 词五维锚词（媒介→光线→配色→材质→镜头），删质量垃圾词
  （8K/octane/masterpiece/hyperdetailed），关键排除折进正向否定句（ARK 无 negative，
  media.generate_image 只发 prompt，negative 仅存档/供质检可读）。

⚠️ 画风改动的权威源是各 seed 文件（knowledge_seed.py / knowledge_seed_cocc.py），
本脚本内的 STYLES 必须与之保持一致；改画风时两处同改。

用法（生产容器内 / 本地）：python scripts/sync_kb_prompts.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncpg

from app.services.scene_blocking import BLOCKING_RULES
from app.services.storyboard import IMAGE_REVIEW_RULES, VIDEO_REVIEW_RULES
from app.settings import settings

# name -> (content 中文说明, positive 英文锚词, negative 存档禁忌)
STYLES: dict[str, tuple[str, str, str]] = {
    "写实科幻": (
        "影视级写实科幻——照片级真实的硬科幻质感，绝非动画/CG：磨损工业金属与功能性机械，"
        "冷调低饱和，体积光穿尘雾，宽银幕变形镜头，物理级真实光影（《银翼杀手2049》《沙丘》式纪实写实的未来）。",
        "photorealistic hard sci-fi, weathered industrial metal, functional practical lighting, "
        "volumetric haze, cool desaturated palette, anamorphic cinematography, physically-based in-camera realism, not cartoon",
        "cartoon, cel shading, glossy plastic CG, flat illustration, cheesy neon",
    ),
    "诺兰IMAX": (
        "诺兰 IMAX 实拍写实——70mm 大画幅极致锐利深焦，冷峻低饱和青灰蓝，混凝土巨构与宏大体量，"
        "自然硬朗方向光，反 CG 的实拍临场感，细腻颗粒；克制不炫技。",
        "large-format IMAX 70mm, ultra-sharp deep-focus clarity, epic wide framing, "
        "natural hard practical light, cold desaturated blue-grey, brutalist concrete vast scale, tactile in-camera realism, no heavy CGI",
        "heavy CGI, saturated candy colors, cartoon, flat illustration, lens gimmick",
    ),
    "史诗奇幻": (
        "托尔金式史诗奇幻电影写实——辽阔中世纪地貌（雪山/古堡/矿坑/大军），Weta 工坊级真实盔甲石造织物，"
        "苔绿岩灰暖金大地色，黄昏逆光云隙光，航拍史诗大远景。",
        "epic high-fantasy, photorealistic cinematic, sweeping medieval landscape, Weta Workshop realism, "
        "weathered armor and stone, earthy muted green-and-gold palette, golden-hour backlight and god rays, vast wide vista, not modern",
        "sci-fi, modern elements, neon, cartoon, anime",
    ),
    "新海诚": (
        "新海诚超精细 2D 动画——天空为主角：层积云与丁达尔光束，钴蓝天到金橙晚霞的冷暖渐变，"
        "强镜头光晕耀斑，都市铁道天台便利店，玻璃反光与光粒子，仰拍天空浅景深散景。",
        "Makoto Shinkai anime style, ultra-detailed painted sky, volumetric god rays, "
        "dramatic lens flare, warm-cool blue-orange gradient, luminous clouds and bokeh, crisp cel-shaded detail, not live-action",
        "photorealistic live action, thick outlines, chibi, dull flat color",
    ),
    "皮克斯": (
        "皮克斯风格化 3D 动画——圆润讨喜造型有神大眼，次表面散射通透皮肤微绒毛，"
        "柔和全局光与干净高光，明快温暖高饱和，浅景深电影级打光；刻意风格化避开恐怖谷。",
        "Pixar-style 3D animation, stylized appealing character, big expressive eyes, subsurface scattering skin, "
        "soft global illumination, clean specular highlights, vibrant warm palette, shallow depth of field, not photorealistic",
        "photorealistic human pores, plastic look, 2D hand-drawn, anime, gritty",
    ),
    "电影感写实": (
        "电影感写实——照片级真实角色与肤质，35/85mm 浅景深自然虚化，柔和动机光，"
        "Kodak Portra 暖调叠 teal-orange 好莱坞调色，细腻胶片颗粒；绝非动画/插画（2026-07-16 精调）",
        "cinematic photorealism, photorealistic characters, natural skin texture, 85mm shallow depth of field, "
        "soft motivated lighting, Kodak Portra tones, teal-and-orange grade, subtle film grain, not illustrated",
        "anime, cartoon, cel shading, plastic skin, 3d render",
    ),
    "阿凡达奇观": (
        "电影感写实科幻·阿凡达奇观——照片级异星生态：生物荧光作主光源，蓝绿靛紫荧光的丛林苔藓水体与生物，"
        "Weta 磷光调色，真实水体光学与体积雾，深海秘境般幽邃，写实而唯美（非动画）",
        "photorealistic alien world, bioluminescent flora and fauna as key light, blue-green-violet glow, "
        "dark lush jungle, phosphorescent Weta-style palette, realistic water optics and volumetric mist, "
        "otherworldly deep-sea ambiance, cinematic anamorphic, not illustrated",
        "anime, cartoon, cel shading, flat illustration, plain daylight, plastic CG",
    ),
}


async def main() -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL)
    for name, body in (("首帧提示词质检", IMAGE_REVIEW_RULES), ("视频提示词质检", VIDEO_REVIEW_RULES)):
        n = await conn.execute(
            "UPDATE kb_entries SET content=$1, updated_at=now() "
            "WHERE kind='skill' AND agent_code='reviewer' AND name=$2 AND scope='global'",
            body, name)
        print(f"{name}: {n}")
    # 导演技能：场景空间规划（2026-07-16 场景组站位锚；同 reviewer——重启不覆盖，改常量后手动同步）
    n = await conn.execute(
        "UPDATE kb_entries SET content=$1, updated_at=now() "
        "WHERE kind='skill' AND agent_code='director' AND name='场景空间规划' AND scope='global'",
        BLOCKING_RULES)
    print(f"场景空间规划: {n}")
    for name, (content, positive, negative) in STYLES.items():
        meta = json.dumps({"positive": positive, "negative": negative}, ensure_ascii=False)
        n = await conn.execute(
            "UPDATE kb_entries SET content=$1, meta = meta || $2::jsonb, updated_at=now() "
            "WHERE kind='prompt_block' AND category='style' AND name=$3 AND scope='global'",
            content, meta, name)
        print(f"画风·{name}: {n}")
    await conn.close()


asyncio.run(main())
