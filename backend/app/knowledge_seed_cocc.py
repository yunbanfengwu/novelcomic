"""cocc-work 知识库迁移 seed：14 种视觉风格 + 24 个动作术语 + 补充景别 + 文风。

来源 D:/myai/cocc-work/backend/scripts/seed_cocc_knowledge.py（cocc_knowledge 表数据），
映射到本项目 kb_entries 结构：中文说明进 content，英文锚词进 meta.positive，禁忌进 meta.negative。
"""
import json

import asyncpg

# (category, name, description=何时召回, content=中文专业说明, positive=英文锚词, negative=禁忌)
COCC_BLOCKS: list[tuple[str, str, str, str, str, str]] = [
    # ═══ 视觉风格（14 种，写实类含"绝非动画"声明）═══
    ("style", "写实科幻", "画风=硬科幻/太空/未来写实",
     "影视级写实科幻——照片级真实的硬科幻质感，绝非动画/CG：磨损工业金属与功能性机械，"
     "冷调低饱和，体积光穿尘雾，宽银幕变形镜头，物理级真实光影（《银翼杀手2049》《沙丘》式纪实写实的未来）。",
     "photorealistic hard sci-fi, weathered industrial metal, functional practical lighting, "
     "volumetric haze, cool desaturated palette, anamorphic cinematography, physically-based in-camera realism, not cartoon",
     "cartoon, cel shading, glossy plastic CG, flat illustration, cheesy neon"),
    ("style", "姜文胶片", "画风=浓烈胶片写实/北方旷野/打斗年代戏",
     "姜文电影浓烈胶片写实——35mm 银盐颗粒、漏光暗角，浓烈暖黄×土褐高对比，北方旷野黄土扬尘烈日逆光，"
     "打斗凌厉尘土飞扬慢门拖影，手持纪实与大景别交替，anamorphic 宽幅。",
     "35mm film grain, photorealistic cinematic, dusty backlit, harsh sunlight, high contrast warm tones, "
     "motion blur martial arts, sweat and dust skin, gunsmoke, anamorphic widescreen",
     "animation, cartoon, illustration"),
    ("style", "张艺谋", "画风=大色块对称/人海调度/东方史诗",
     "张艺谋美学写实呈现——极致对称大色块构图，几何阵列人海调度（千人列阵/旗海/伞阵），"
     "大红/明黄/翠绿/靛蓝整片铺陈色彩即情绪，宫墙庭院菊海竹林，硬光造型逆光剪影灯笼暖辉。",
     "cinematic photorealistic, perfect symmetry, bold saturated color blocks (red/yellow/green), "
     "epic crowd choreography, oriental classical, silk and lanterns, dramatic backlight, ceremonial, 8K, anamorphic",
     "cartoon, flat illustration, desaturated grey, cluttered composition, cheap 3D"),
    ("style", "王家卫", "画风=霓虹暧昧/都市疏离/雨夜情绪",
     "王家卫质感写实——35mm 胶片颗粒漏光暗角，青绿品红对冲暖黄路灯，1960s 香港逼仄走廊铁皮排档雨夜街角，"
     "低照度氛围光烟雾光晕，浅景深前景遮挡偷窥构图，step-printing 抽帧拖影。",
     "35mm film grain, neon-soaked, high saturation teal-and-magenta, shallow depth of field, "
     "foreground occlusion, step-printing motion blur, moody humid warm tones, 1960s Hong Kong, cinematic photorealistic",
     "animation, cartoon, bright even lighting, deep focus, modern minimal"),
    ("style", "诺兰IMAX", "画风=冷峻宏大/硬核写实/巨构奇观",
     "诺兰 IMAX 实拍写实——70mm 大画幅极致锐利深焦，冷峻低饱和青灰蓝，混凝土巨构与宏大体量，"
     "自然硬朗方向光，反 CG 的实拍临场感，细腻颗粒；克制不炫技。",
     "large-format IMAX 70mm, ultra-sharp deep-focus clarity, epic wide framing, "
     "natural hard practical light, cold desaturated blue-grey, brutalist concrete vast scale, tactile in-camera realism, no heavy CGI",
     "heavy CGI, saturated candy colors, cartoon, flat illustration, lens gimmick"),
    ("style", "昆汀复古", "画风=70s暴力美学/复古胶片/B级片",
     "昆汀复古 grindhouse——35/70mm 胶片划痕褪色漏光，焦黄酒红橙褐 70s 色科学，"
     "公路汽车旅馆酒吧年代道具，夸张喷溅定格残酷瞬间，脚部特写后备箱视角急推变焦。",
     "70s grindhouse, 35mm film grain, retro warm palette, stylized violence, trunk shot, "
     "snap zoom, scratched faded film, cinematic photorealistic",
     "animation, clean digital look, cold minimal"),
    ("style", "赛博朋克", "画风=霓虹雨夜/反乌托邦/高科技低生活",
     "赛博朋克反乌托邦——青橙撞色品红电蓝霓虹，摩天楼全息广告密集招牌蒸汽雨水，"
     "霓虹光污染体积光束穿雨雾湿地面镜面反射，金属义肢污渍磨损高科技质感，低角度仰拍巨构霓虹散景。",
     "cyberpunk, neon-noir, rain-soaked night, holographic ads, teal-orange, volumetric neon, "
     "Blade Runner, wet reflective streets, photorealistic, cinematic, 8K",
     "bright daytime, cartoon flat, warm pastoral"),
    ("style", "史诗奇幻", "画风=指环王式/中世纪/宏大幻想",
     "托尔金式史诗奇幻电影写实——辽阔中世纪地貌（雪山/古堡/矿坑/大军），Weta 工坊级真实盔甲石造织物，"
     "苔绿岩灰暖金大地色，黄昏逆光云隙光，航拍史诗大远景。",
     "epic high-fantasy, photorealistic cinematic, sweeping medieval landscape, Weta Workshop realism, "
     "weathered armor and stone, earthy muted green-and-gold palette, golden-hour backlight and god rays, vast wide vista, not modern",
     "sci-fi, modern elements, neon, cartoon, anime"),
    ("style", "韦斯安德森", "画风=强迫症对称/马卡龙糖果色/复古精致",
     "韦斯·安德森对称绘本美学——极致中心对称正面平视人物居中，薄荷绿鹅黄粉红米杏马卡龙粉彩，"
     "复古旅馆列车橱柜标本式陈列，均匀柔和平光明信片般干净，90°横摇定格构图舞台框景。",
     "perfectly symmetrical, centered composition, flat front-on, pastel macaron palette, "
     "retro whimsical, dollhouse production design, soft even lighting, storybook, cinematic",
     "cluttered composition, handheld shake, high contrast dark, gritty realism"),
    ("style", "黑色电影", "画风=黑白高反差/雨夜悬疑/40s noir",
     "经典黑色电影——黑白 35mm 胶片颗粒暗角，极高明暗对比深黑阴影，雨夜都市百叶窗霓虹招牌烟雾酒吧，"
     "硬质单点侧光百叶窗投影条纹低调照明，荷兰角剪影低角度悬疑构图。",
     "film noir, black and white, high contrast chiaroscuro, venetian blind shadows, "
     "low-key lighting, rain-soaked night, cigarette smoke, 1940s, cinematic",
     "color, bright flat lighting, cartoon, high saturation"),
    ("style", "吉卜力", "画风=宫崎骏/温润治愈/田园自然 2D 手绘",
     "吉卜力 2D 手绘动画——赛璐璐手绘柔和水彩背景干净线条，草木绿天空蓝暖阳黄清新通透，"
     "草甸云海欧式小镇老屋厨房生活细节，柔和自然光斑驳树影，开阔风景定格留白呼吸感。",
     "Studio Ghibli, hand-drawn 2D animation, Miyazaki, soft watercolor background, lush nature, "
     "warm natural light, gentle pastel, anime, wholesome",
     "photorealistic, 3D, dark gore, high contrast"),
    ("style", "新海诚", "画风=极致光影/唯美天空/都市黄昏动画",
     "新海诚超精细 2D 动画——天空为主角：层积云与丁达尔光束，钴蓝天到金橙晚霞的冷暖渐变，"
     "强镜头光晕耀斑，都市铁道天台便利店，玻璃反光与光粒子，仰拍天空浅景深散景。",
     "Makoto Shinkai anime style, ultra-detailed painted sky, volumetric god rays, "
     "dramatic lens flare, warm-cool blue-orange gradient, luminous clouds and bokeh, crisp cel-shaded detail, not live-action",
     "photorealistic live action, thick outlines, chibi, dull flat color"),
    ("style", "皮克斯", "画风=圆润可爱/合家欢/风格化 3D 动画",
     "皮克斯风格化 3D 动画——圆润讨喜造型有神大眼，次表面散射通透皮肤微绒毛，"
     "柔和全局光与干净高光，明快温暖高饱和，浅景深电影级打光；刻意风格化避开恐怖谷。",
     "Pixar-style 3D animation, stylized appealing character, big expressive eyes, subsurface scattering skin, "
     "soft global illumination, clean specular highlights, vibrant warm palette, shallow depth of field, not photorealistic",
     "photorealistic human pores, plastic look, 2D hand-drawn, anime, gritty"),
    ("style", "中国水墨", "画风=国风写意/留白/墨分五色",
     "中国传统水墨意境——宣纸墨色浓淡干湿晕染飞白笔触少量朱砂石青点染，黑白灰为骨大面积留白素雅，"
     "远山云雾孤舟松竹亭台虚实相生，无明确光源以墨色表体积烟云氤氲，散点透视立轴构图负空间。",
     "Chinese ink wash painting, sumi-e, xuan paper texture, negative space, misty mountains, "
     "monochrome ink gradient, flying-white brushstroke, traditional, elegant",
     "photorealistic, 3D render, full composition, high saturation"),
    # ═══ 补充景别 ═══
    ("camera", "大特写", "眼睛/伤口/关键物件极局部放大/强张力悬念",
     "眼睛/伤口/物件极局部充满画面，制造强烈张力与悬念",
     "extreme close-up, macro detail, intense dramatic tension, single detail fills frame",
     "wide shot"),
    # ═══ 动作语言：武术格斗（8）═══
    ("motion", "直拳", "出拳/正面攻击", "身体前压拳锋直线爆发，肩胯发力，命中瞬间气浪汗水迸溅",
     "straight punch impact, forward lunge, explosive power, sweat spray on impact", ""),
    ("motion", "勾拳", "重击/近身缠斗", "腰胯拧转带横向弧线重拳，下颌被击偏转，慢门拖影",
     "hook punch, torso rotation, jaw snap, motion blur arc", ""),
    ("motion", "回旋踢", "腿法/高位攻击", "单腿支撑身体旋转另一腿高位横扫，腾空弧线张力",
     "spinning roundhouse kick, aerial arc, dynamic rotation", ""),
    ("motion", "扫堂腿", "下盘攻击/放倒对手", "低身下蹲贴地横扫扬起尘土，对手失衡腾空",
     "low sweep kick, dust kicked up, opponent losing balance airborne", ""),
    ("motion", "格挡招架", "防御/兵器相接", "前臂或兵器硬碰交击的火花与震动，力道传导的僵直",
     "block and parry, clashing impact sparks, force vibration", ""),
    ("motion", "擒拿摔投", "近身制服/摔技", "锁腕别臂过肩摔，关节反折角度，对手腾空翻落",
     "grappling throw, joint lock, over-shoulder throw, opponent flipped airborne", ""),
    ("motion", "拔刀亮招", "冷兵器对决开场/威慑", "出鞘瞬间寒光残影蓄势杀气，身形低伏待发",
     "iaido draw, blade gleam, killing intent stance, low crouch ready", ""),
    ("motion", "兵器对拼", "刀剑交锋", "刀剑相交迸射火花，贴身缠斗金属摩擦与崩劲",
     "weapon clash sparks, blade grinding, close-quarters struggle", ""),
    # ═══ 动作语言：超英特技（8）═══
    ("motion", "三点着地", "高处落地/帅气登场", "单膝跪地一拳撑地，地面龟裂尘土环形外扩",
     "superhero landing, ground crack, radial dust burst", ""),
    ("motion", "凌空跃起", "起跳/爆发腾空", "爆发蹬地腾空身体舒展拉长，披风衣摆飞扬背景速度线",
     "explosive leap, cape flutter, speed lines, stretched silhouette", ""),
    ("motion", "飞檐走壁", "跑酷/楼宇穿梭", "蹬墙借力连续翻越障碍的流畅动势",
     "parkour wall-run, fluid vaulting, urban traversal", ""),
    ("motion", "空中翻腾", "空翻/闪避", "高空多周翻转收身展身弧线轨迹与运动残影",
     "aerial flip, motion trail, tucked rotation", ""),
    ("motion", "蹬墙变向", "急转/变向爆发", "踩墙急转方向瞬间变向的爆发力",
     "wall kick redirect, sudden direction change burst", ""),
    ("motion", "空中接招", "空中拦截/抓取", "腾跃中单手抓取或拦截的精准定格瞬间",
     "midair catch, precise freeze-frame interception", ""),
    ("motion", "破窗冲入", "突入/破窗", "玻璃四溅慢镜身体破窗而入的冲击",
     "crashing through glass, slow-motion shards, dynamic entry", ""),
    ("motion", "冲击波震退", "能量爆发/击退", "拳力能量外放环形冲击波，周围人物碎物被震飞",
     "shockwave knockback, radial energy burst, debris flying", ""),
    # ═══ 动作语言：轻功武侠（4）═══
    ("motion", "踏水掠行", "轻功/水面飞掠", "脚尖点水疾掠水面涟漪水珠飞溅轻盈无重",
     "water-skimming, ripples and droplets, weightless glide, wuxia", ""),
    ("motion", "飞身上墙", "轻功纵跃/上房", "借力直窜数丈衣袂翻飞的飘逸纵跃",
     "soaring leap, flowing robes, effortless ascent, wuxia", ""),
    ("motion", "凌空御剑", "御剑飞行/仙侠", "脚踏飞剑凌空悬浮长发衣带飘举",
     "flying sword stance, levitating, hair and sash flowing, xianxia", ""),
    ("motion", "旋身腾挪", "闪避/身法", "连续侧空翻闪避身形如残影鬼魅",
     "afterimage dodge, consecutive aerial cartwheels, ghostly agility", ""),
    # ═══ 动作语言：受击反应（4）═══
    ("motion", "中招踉跄", "受击/挨打", "受击后上身后仰脚步踉跄失衡痛苦表情",
     "staggering hit, recoiling, losing balance, pained expression", ""),
    ("motion", "被击飞", "重击/击飞", "重击腾空倒飞四肢失控甩动撞向障碍",
     "knocked flying, limbs flailing, crashing into obstacle", ""),
    ("motion", "翻滚卸力", "落地/卸力", "落地顺势翻滚卸冲击迅速起身",
     "combat roll recover, momentum dissipation, quick recovery", ""),
    ("motion", "慢镜受击", "子弹时间/高潮打击", "子弹时间慢动作汗血珠悬浮冲击波纹扩散",
     "slow-motion impact, bullet time, suspended droplets, shockwave ripple", ""),
]

# 文风知识（kind=knowledge，写作员工用）
COCC_KNOWLEDGE: list[tuple[str, str, str, str]] = [
    ("writing_style", "金庸武侠", "文风=武侠/古风时召回",
     "白描见骨、对仗工整、古风对白、招式与心境交织，克制而有侠气。"),
]


async def seed_cocc_knowledge(pool: asyncpg.Pool) -> int:
    """幂等迁移 cocc-work 知识：按 (scope,kind,category,name) 不存在才插。"""
    inserted = 0
    async with pool.acquire() as conn:
        for category, name, desc, content, positive, negative in COCC_BLOCKS:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='prompt_block' "
                "AND category=$1 AND name=$2", category, name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, meta) "
                "VALUES ('global','prompt_block',$1,$2,$3,$4,$5::jsonb)",
                category, name, desc, content,
                json.dumps({"positive": positive, "negative": negative, "source": "cocc-work"},
                           ensure_ascii=False),
            )
            inserted += 1
        for category, name, desc, content in COCC_KNOWLEDGE:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='knowledge' "
                "AND category=$1 AND name=$2", category, name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, meta) "
                "VALUES ('global','knowledge',$1,$2,$3,$4,'{\"source\":\"cocc-work\"}'::jsonb)",
                category, name, desc, content,
            )
            inserted += 1
    return inserted
