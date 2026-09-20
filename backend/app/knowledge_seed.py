"""公共知识首批 seed：镜头语言 / 运镜 / 肢体动作 / 视觉风格 结构化专业提示词块。

核心原则2：专业提示词是知识资产，生成时按内容动态召回装配。
块结构参考 mneme knowledge-driven-storyboard（正/负词 + 参数，可组合不打包）。
"""
import json

import asyncpg

# (category, name, description=何时召回, content=中文专业说明, positive, negative)
SEED_BLOCKS: list[tuple[str, str, str, str, str, str]] = [
    # ── 镜头语言：景别 ──
    ("camera", "大远景", "宏大开场/交代地理环境/史诗感/孤独渺小",
     "极端远距离，人物占画面极小比例，强调环境吞噬感与空间尺度",
     "extreme long shot, vast landscape, tiny figure in frame, epic scale, environmental storytelling",
     "close-up, cropped face"),
    ("camera", "远景", "交代场景全貌/人物与环境关系/段落开头",
     "人物全身可见且环境占主导，用于建立空间方位",
     "long shot, establishing shot, full environment visible, character in context",
     ""),
    ("camera", "全景", "展示人物全身动作/肢体表演/走位",
     "人物全身恰好充满画面，动作可读性最高",
     "full shot, full body in frame, clear action staging",
     "cropped limbs"),
    ("camera", "中景", "对话/双人互动/半身表演",
     "腰部以上，兼顾表情与肢体，叙事最常用",
     "medium shot, waist-up framing, conversational distance",
     ""),
    ("camera", "近景", "情绪递进/表情细节/重要台词",
     "胸部以上，表情为主，压迫感开始出现",
     "close shot, chest-up framing, facial expression focus",
     ""),
    ("camera", "特写", "情绪爆发/关键道具/眼神/转折点",
     "面部或物件充满画面，情绪与细节的最强放大器",
     "close-up, extreme detail, emotional intensity, shallow depth of field",
     "wide angle distortion"),
    ("camera", "大特写", "全段最重要信息/微小关键物/接触瞬间——关键信息独占一镜",
     "眼睛/指尖/接触点级别的极端放大，通常是全段情绪支点，哪怕只有2秒也独占一镜",
     "extreme close-up, macro detail, single critical element filling frame, razor-thin depth of field",
     "full body, wide shot"),
    ("camera", "过肩镜头", "对峙/审讯/谈判两人戏",
     "越过前景人物肩膀拍对面，制造在场感与关系张力",
     "over-the-shoulder shot, two-person confrontation, foreground shoulder framing",
     ""),
    ("camera", "低角度仰拍", "表现威严/压迫/力量感/反派登场",
     "镜头低于主体向上仰拍，主体显得高大有压迫性",
     "low angle shot, looking up, imposing presence, towering figure",
     ""),
    ("camera", "高角度俯拍", "表现弱小/无助/上帝视角/群像调度",
     "镜头高于主体向下俯拍，主体显得渺小",
     "high angle shot, bird's eye view, vulnerable subject, top-down composition",
     ""),
    # ── 机位角度（独立正交轴；景别×角度=情绪，见 docs/arch/storyboard-prompt-spec.md）──
    ("angle", "平视", "中性叙事/对话/日常——默认角度",
     "镜头与主体视线等高，中性自然，观众与角色平等",
     "eye-level shot, neutral perspective, natural framing",
     ""),
    ("angle", "仰拍", "威压/崇拜/力量登场；特写+仰拍=威压崇拜",
     "镜头低于主体向上拍，主体高大有压迫感；配特写表崇拜威压，配大远景表恢弘",
     "low angle shot, looking up at subject, imposing towering presence",
     ""),
    ("angle", "俯拍", "脆弱/无助/被观察；特写+俯拍=脆弱恐惧",
     "镜头高于主体向下拍，主体渺小无助；与仰拍对切=情绪反转（坠落→翱翔）",
     "high angle shot, looking down at subject, vulnerable diminished figure",
     ""),
    ("angle", "鸟瞰", "地理交代/命运感/群像调度；远景+鸟瞰=渺小与空间",
     "垂直或近垂直向下的上帝视角，展示地理关系与个体渺小",
     "bird's eye view, top-down aerial perspective, god's eye composition",
     ""),
    ("angle", "过肩", "对峙/谈判/两人关系张力",
     "越过前景人物肩膀拍对面主体，前景肩部虚化入画建立轴线",
     "over-the-shoulder shot, foreground shoulder bokeh, two-person axis",
     ""),
    ("angle", "主观POV", "代入角色视线/发现/惊悚窥视",
     "第一人称视角，镜头即角色眼睛，常配轻微晃动",
     "first-person POV shot, seeing through character's eyes, immersive subjective view",
     ""),
    ("angle", "荷兰角", "不安/失衡/精神异常；中景+荷兰角=日常不安",
     "画面水平线倾斜，制造心理失衡与紧张",
     "dutch angle, tilted horizon, psychological unease",
     "level horizon"),
    # ── 焦段感（光圈效果化：浅景深/背景压缩由焦段词携带；克制原则：默认35mm，有理由才偏离）──
    ("lens", "16mm超广角", "史诗大场面/建筑尺度/翱翔释放镜头",
     "极强透视纵深与空间夸张，边缘轻微拉伸，宏大感",
     "16mm ultra wide angle lens, exaggerated perspective depth, epic spatial scale",
     "telephoto compression"),
    ("lens", "24mm广角", "环境交代/幽闭或开阔空间感/POV",
     "空间感强，前后景关系清晰，近摄轻微畸变（《1917》地堡用广角制造幽闭）",
     "24mm wide angle lens, strong sense of space, environmental context",
     ""),
    ("lens", "35mm标准", "叙事默认焦段/跟拍/中景动作——《1917》式基准",
     "接近人眼视野的叙事基准焦段，透视自然（默认焦段，无理由不偏离）",
     "35mm lens, natural perspective, cinematic standard framing",
     ""),
    ("lens", "50mm标准", "对话/半身/自然人像",
     "无畸变的自然人像焦段，主体与背景关系真实",
     "50mm lens, natural portrait perspective, true-to-eye rendering",
     ""),
    ("lens", "85mm长焦", "特写/情绪脸/减少背景信息（《1917》河流47mm同理）",
     "背景压缩+奶油虚化，把注意力压在主体脸上，浅景深",
     "85mm telephoto lens, compressed background, creamy bokeh, shallow depth of field",
     "wide angle distortion"),
    ("lens", "100mm微距", "接触瞬间/眼球/微小关键物的大特写",
     "微距级放大与极浅景深，纹理细节纤毫毕现",
     "100mm macro lens, extreme magnification, razor-thin focus plane, intricate texture detail",
     ""),
    # ── 光效（布光效果化：写灯具产生的画面效果，不写灯具——BR2049 256盏Fresnel→"流动水波光"）──
    ("lighting", "晨昏侧逆光", "黎明黄昏/离别启程/轮廓勾勒",
     "低角度暖光从侧后方勾出发丝与轮廓边缘，脸部留暗部层次",
     "golden hour rim light, low sun backlighting, glowing hair edges, soft shadow falloff",
     "flat lighting"),
    ("lighting", "丁达尔光柱", "神圣感/水下或林间/希望意象",
     "体积光束穿透介质（水体/雾/林隙），悬浮微粒可见",
     "volumetric god rays, light shafts through medium, visible floating particles",
     ""),
    ("lighting", "生物荧光", "深海/夜晚异星/奇观唯美场景",
     "黑暗中生物体自发光为唯一或主要光源，蓝绿金冷光映照主体",
     "bioluminescent glow as key light, self-illuminating organisms in darkness, cold blue-green luminescence",
     "daylight"),
    ("lighting", "剪影逆光", "宿命感/告别/巨物登场",
     "主体全黑剪影衬亮背景，形体轮廓叙事",
     "full silhouette against bright background, backlit figure, shape-driven composition",
     ""),
    ("lighting", "硬光高对比", "紧张对峙/审讯/黑色电影",
     "单侧硬光切割面部，明暗交界锐利，阴影浓重",
     "hard key light, high contrast chiaroscuro, sharp shadow edges, noir mood",
     "soft diffused light"),
    ("lighting", "柔光漫射", "温情/回忆/日常安宁",
     "大面积柔化光源，阴影柔和过渡，肤质细腻",
     "soft diffused lighting, gentle shadow gradients, flattering skin tones",
     ""),
    ("lighting", "水下焦散", "水下场景专用/真实水体光学",
     "水面折射在主体与环境上投下流动的网状光斑",
     "underwater caustics, rippling light patterns, refracted dancing highlights",
     ""),
    ("lighting", "流动环绕光", "对话中光影缓慢流动/神迹感（BR2049水波光效果化）",
     "光源绕主体缓慢流转，明暗在脸上呼吸般移动",
     "slowly moving wraparound light, breathing light patterns drifting across subject",
     ""),
    ("lighting", "夜市霓虹湿反", "雨夜街头/都市夜景/霓虹氛围（Seedance案例：深夜临街咖啡馆/赛博街角沉淀）",
     "暖黄或霓虹灯光透出，地面湿润反光，光斑在雨水与玻璃上晕开",
     "neon signs reflecting on wet pavement, warm window glow at night, rain-streaked glass bokeh, moody urban night",
     "flat daylight"),
    ("lighting", "暖黄室内烟火气", "温馨日常/餐馆咖啡馆/怀旧生活场景（Seedance案例：暖调氛围感场景沉淀）",
     "暖黄色灯光铺满室内，热气与光晕细节清晰，温暖治愈的生活质感",
     "warm tungsten interior glow, cozy amber lighting, visible steam catching light, soft nostalgic homely warmth",
     "cold sterile lighting"),
    # ── 运镜 ──
    ("camera_move", "推镜", "情绪聚焦/发现细节/心理压近",
     "镜头向主体缓慢推进，注意力收束，紧张感渐强",
     "slow push in, dolly in, gradually approaching subject, building tension",
     "static camera"),
    ("camera_move", "拉镜", "揭示环境/抽离情绪/段落收尾",
     "镜头远离主体拉出，信息量展开或情感疏离",
     "pull back, dolly out, revealing wider context, emotional distancing",
     ""),
    ("camera_move", "摇镜", "跟随视线/扫视环境/两主体间转移",
     "机位不动水平/垂直转动，模拟转头观察",
     "pan shot, smooth horizontal sweep, following gaze",
     ""),
    ("camera_move", "移镜", "平行跟随/穿越场景/展示纵深",
     "机位横向或纵向平移，产生空间穿行感",
     "tracking shot, lateral camera movement, traveling through scene",
     ""),
    ("camera_move", "跟拍", "追逐/行走对话/持续动作",
     "镜头保持距离跟随主体移动，主体稳定环境流动",
     "follow shot, camera following subject, steady framing with moving background",
     ""),
    ("camera_move", "升降镜头", "宏大揭示/情绪升华/开场落幕",
     "镜头垂直升降，常配合大远景做史诗级揭示",
     "crane shot, ascending camera, sweeping vertical reveal",
     ""),
    ("camera_move", "手持晃动", "紧张/混乱/纪实感/打斗现场",
     "轻微不规则晃动，代入第一现场的不安",
     "handheld camera, subtle shake, documentary realism, chaotic energy",
     "smooth stabilized footage"),
    ("camera_move", "环绕镜头", "主角高光时刻/立体展示/对峙升级",
     "镜头绕主体旋转，强调三维存在感与戏剧性",
     "orbit shot, camera circling around subject, 360 rotation, dramatic emphasis",
     ""),
    # ── 专业运镜（Seedance 官方四十法沉淀：cuts 内运镜叙事的词汇资产，电影级质感）──
    ("camera_move", "希区柯克变焦", "悬疑揭示/时空扭曲感/主角认知冲击瞬间",
     "推轨与变焦反向操作：主体大小不变而背景急速压缩或拉伸，制造眩晕与不安",
     "dolly zoom, vertigo effect, subject stays constant while background compresses, hitchcock zoom",
     "static lens"),
    ("camera_move", "升格慢动作", "关键瞬间仪式感/命中定格/水花飞溅特写——仅在明确需要仪式感处使用（默认真实速度）",
     "高帧率升格：动作以电影级慢动作呈现，细节纤毫毕现（与全局'禁止慢动作'约束互斥，使用时须显式声明）",
     "slow motion, high frame rate ramping, cinematic speed ramp, suspended droplets and debris",
     "normal speed"),
    ("camera_move", "高速螺旋环绕", "能量爆发/终结技/华丽高潮",
     "镜头绕主体高速螺旋上升或收紧，眩晕式华丽感",
     "high-speed spiral orbit, rapidly circling ascending camera, dizzying dynamic energy",
     "slow static shot"),
    ("camera_move", "俯冲镜头", "紧张突袭/坠落追随/冲击力开场",
     "镜头由高处向主体快速俯冲，压迫感与速度感拉满",
     "swooping dive shot, camera plunging downward toward subject, aggressive momentum",
     ""),
    ("camera_move", "快速拉升", "揭晓全景/规模震撼/段落收束",
     "镜头快速垂直拉升远离主体，瞬间展开地理全貌",
     "rapid pull-up ascent, camera rising fast away from subject, sweeping aerial reveal",
     ""),
    ("camera_move", "匹配剪辑转场", "时空跳跃/蒙太奇衔接/形状动作接续",
     "以相似形状或同向动作衔接两个时空的画面（Match Cut），无缝转场",
     "match cut transition, graphic match between scenes, seamless spatial-temporal jump",
     ""),
    ("camera_move", "焦外虚化缓移", "氛围铺垫/窥视感/情绪留白",
     "浅景深下镜头缓慢平移，焦外光斑流动，主体渐次清晰",
     "shallow focus slow drift, bokeh foreground sweep, subject emerging from soft blur",
     ""),
    ("camera_move", "微距推近", "产品细节/纹理特写/微小关键物揭示",
     "微距景别下缓慢推进，纹理与材质细节逐渐充满画面",
     "macro push-in, extreme close-up slowly advancing, intricate texture filling frame",
     ""),
    ("camera_move", "推拉结合", "悬念揭示/先聚焦后展开的两段式叙事（单镜内先推后拉需拆成两切）",
     "先推近特写锁定细节，再拉远展开全景关系——以 cuts 两段表达，不在单切内复合",
     "push-in to close-up then pull-back reveal, two-beat focus-then-context camera phrase",
     ""),
    ("camera_move", "一镜到底感", "沉浸漫游/连续空间穿越/长镜头调度",
     "无剪辑感的连续运动长镜，镜头在空间中流畅穿行，调度感强",
     "continuous unbroken long take feel, flowing oner, seamless traveling through space",
     "jump cuts"),
    # ── 肢体动作 ──
    ("motion", "武打近身格斗", "打斗/交手/近身缠斗镜头",
     "拳肘膝的快速连击与格挡，重心低、发力可见",
     "dynamic martial arts combat, rapid strikes and blocks, low stance, impact frames, motion blur on limbs",
     "stiff pose, floating feet"),
    ("motion", "拔刀/亮兵器", "冷兵器对决开场/威慑瞬间",
     "缓慢拔刃与骤然亮刃的对比，刃面反光",
     "drawing blade slowly, sudden flash of steel, blade catching light, duel stance",
     ""),
    ("motion", "奔跑追逐", "追逃/赶路/紧急冲刺",
     "身体前倾、步幅拉大、衣摆发丝后飞",
     "full sprint, leaning forward, hair and clothes trailing, urgency",
     "casual walking"),
    ("motion", "坠落/跃下", "跳楼/坠崖/飞身而下",
     "四肢舒展或蜷缩的失重姿态，环境速度线",
     "falling through air, weightless pose, wind-swept clothing, vertigo perspective",
     ""),
    ("motion", "哭泣崩溃", "悲伤爆发/得知噩耗",
     "肩膀颤抖、掩面或跪地，收缩性肢体语言",
     "shoulders trembling, covering face, collapsing to knees, grief-stricken body language",
     "smiling"),
    ("motion", "隐忍愤怒", "压抑怒火/隐忍对峙",
     "握拳指节发白、下颌绷紧、目光低垂后抬起",
     "clenched fists, tense jaw, slowly raising glare, suppressed rage",
     ""),
    ("motion", "拥抱重逢", "久别重逢/告别/安慰",
     "冲入怀中或迟疑后相拥，手指收紧",
     "rushing embrace, fingers gripping tightly, emotional reunion",
     ""),
    ("motion", "回眸", "离别/惊觉/宿命感瞬间",
     "行进中停步回头，发丝随动作甩动",
     "looking back over shoulder, hair swinging with the turn, poignant pause",
     ""),
    # ── 视觉风格 ──
    ("style", "日漫赛璐璐", "画风=日漫/轻小说/热血番",
     "干净硬边描线+平涂+高饱和，赛璐璐质感",
     "anime style, cel shading, clean lineart, vibrant flat colors, high quality anime key visual",
     "photorealistic, 3d render, western cartoon"),
    ("style", "国漫水墨", "画风=东方玄幻/仙侠/古风",
     "水墨晕染+留白+淡彩，东方意境",
     "chinese ink wash painting style, flowing brushstrokes, negative space, subtle color accents, wuxia aesthetic",
     "neon colors, cyberpunk"),
    ("style", "美漫厚涂", "画风=硬汉/都市/超英",
     "厚涂笔触+强对比光影+粗犷线条",
     "western comic style, bold inking, heavy shadows, painterly rendering, dramatic contrast",
     "chibi, moe style"),
    ("style", "电影感写实", "画风=写实短剧/都市情感",
     "电影感写实——照片级真实角色与肤质，35/85mm 浅景深自然虚化，柔和动机光，"
     "Kodak Portra 暖调叠 teal-orange 好莱坞调色，细腻胶片颗粒；绝非动画/插画（2026-07-16 精调）",
     "cinematic photorealism, photorealistic characters, natural skin texture, 85mm shallow depth of field, "
     "soft motivated lighting, Kodak Portra tones, teal-and-orange grade, subtle film grain, not illustrated",
     "anime, cartoon, cel shading, plastic skin, 3d render"),
    ("style", "阿凡达奇观", "画风=写实科幻奇观/异星生态/深海秘境（项目《深澜纪》实测定稿沉淀）",
     "电影感写实科幻·阿凡达奇观——照片级异星生态：生物荧光作主光源，蓝绿靛紫荧光的丛林苔藓水体与生物，"
     "Weta 磷光调色，真实水体光学与体积雾，深海秘境般幽邃，写实而唯美（非动画）",
     "photorealistic alien world, bioluminescent flora and fauna as key light, blue-green-violet glow, "
     "dark lush jungle, phosphorescent Weta-style palette, realistic water optics and volumetric mist, "
     "otherworldly deep-sea ambiance, cinematic anamorphic, not illustrated",
     "anime, cartoon, cel shading, flat illustration, plain daylight, plastic CG"),
    ("style", "粘土定格", "画风=粘土手工/定格动画/温馨童趣（Seedance案例：粘土风沉淀）",
     "精致粘土造型+手工纹理（指纹痕迹/真实材质）+停格动画帧间移动感，温暖柔光",
     "claymation style, stop-motion animation, handcrafted clay texture with visible fingerprints, "
     "miniature diorama world, warm soft lighting, charming handmade feel",
     "photorealistic, smooth 3d render"),
    ("style", "毛毡手作", "画风=毛毡玩偶/软萌治愈/儿童向（Seedance案例：毛毡风格沉淀）",
     "羊毛毡质感角色与道具，纤维细节可见，柔软得仿佛可以触摸的温馨画面",
     "needle felted wool style, fuzzy felt texture with visible fibers, soft plush handmade craft aesthetic, "
     "cozy heartwarming miniature scene",
     "hard surface, glossy plastic, photorealistic"),
    ("style", "像素游戏", "画风=复古游戏/8bit16bit/游戏演出（Seedance案例：魂斗罗式打斗沉淀）",
     "复古像素游戏画面：大颗粒像素+有限调色板+游戏HUD式构图，动作逐帧顿挫",
     "retro pixel art style, 16-bit game aesthetic, chunky pixels, limited color palette, "
     "side-scroller game framing, frame-by-frame sprite animation feel",
     "smooth gradients, photorealistic, high polygon 3d"),
    # ── 节奏（AI 视频对抗块：模型默认输出缓慢漂移运镜+慢动作，必须显式对抗）──
    ("pace", "快速利落", "动作爆点/打斗/追逐/坠落/紧张段——对抗AI默认慢动作",
     "动作真实速度甚至略快，起止干脆，禁止慢动作与缓慢漂移",
     "fast decisive motion, real-time speed, explosive energy, snappy crisp movement, no slow motion, no camera drift",
     "slow motion, sluggish movement, drifting camera, floaty"),
    ("pace", "舒展流畅", "情绪释放/飞翔/滑翔/抒情段——运动要有速度感的流畅",
     "大幅度流畅运动，有惯性与速度感，不是慢动作",
     "sweeping graceful motion with real momentum, flowing movement, dynamic speed",
     "slow motion, static"),
    ("pace", "静止凝滞", "静场/对峙/凝视/呼吸感镜头——固定镜头必须真固定",
     "机位完全锁定，画面近乎静止，只有微小生命性运动（呼吸/发丝/光的呼吸）",
     "locked-off camera, absolutely static framing, only subtle micro movements, breathing stillness",
     "camera drift, panning, zooming"),
    # ── 设定图版式（要素出图专用）──
    ("sheet", "角色设定图", "生成角色身份版/设定图时必用",
     "角色参考设定图版式：三视图+特写+表情+动作+色板，白底排版。注意：ARK 生图不支持 negative，"
     "约束必须写进正向词——同一人物贯穿全部面板/无第二人物/无文字标签/表情与主图同风格",
     "character reference sheet of ONE single character, the exact same person repeated across every panel, "
     "character turnaround three views (front view, side view, back view, full body, identical outfit in all views), "
     "close-up portrait, four cinematic expression studies of the same face in the same rendering style as the "
     "main portrait — subtle asymmetrical micro-expressions captured mid-emotion like candid film stills: "
     "a restrained joy barely lifting one corner of the mouth, a cold hardening gaze, a quiet sorrow with "
     "distant unfocused eyes, a sudden alert wariness; realistic catchlights in the eyes, natural skin tension, "
     "dry eyes with no tears, gaze slightly off-camera, never posed at camera, absolutely no exaggerated grin, "
     "no bulging wide eyes, no stock-photo mugshot expression, "
     "two dynamic action poses of the exact same character with identical "
     "face, age, build and costume as the main portrait, color palette swatches at corner, "
     "clean white background, no text, no labels, no captions, strictly no other person or child in frame, "
     "no extra accessories beyond the character description, professional character design sheet layout",
     "second character, extra person, child, anime expression panels mixed with realistic style, "
     "exaggerated grimace, stock photo smile, posed mugshot expression, "
     "inconsistent outfit between views, text, gibberish captions, cropped views, messy layout"),
    ("sheet", "分镜宫格草图", "章级分镜总览宫格故事板必用（模板方案：格线/中央定位镜号/留空格由代码"
     "预渲染成模板参考图，模型在白格内画全彩故事板画面）——此块只管画面质感，版式不进提示词",
     "宫格故事板质感（彩色版 2026-07-12）：每格一幅全彩故事板画面——构图/站位/动势清晰，"
     "色彩与光线服务本镜情绪，整张遵循项目画风；同一角色造型与服色跨格一致（有设定图按设定图还原）；"
     "格间空间连贯；严禁画面中出现任何文字与数字（格中央定位数字须被画面完全覆盖）",
     "vivid full-color storyboard panels, cinematic composition sketches, "
     "clear staging and blocking, expressive rough concept-art painting, "
     "consistent character designs and costume colors across panels, "
     "coherent spatial continuity between panels, no text, no numbers, no captions",
     "black and white, monochrome line art, text, numbers, speech bubbles, watermark, "
     "photo collage, inconsistent character design between panels"),
    ("sheet", "生物设定图", "非人形生物/坐骑/怪兽要素出设定图时必用（人形版式会把生物拟人化）",
     "生物概念设定图版式：全身主视图+俯视/侧视+体型比例参照+皮肤纹理与发光纹样特写+色板；"
     "严禁人形三视图/表情表词汇（会诱发拟人化身乱入）",
     "creature concept design sheet of ONE single non-humanoid creature, large main full-body view, "
     "top view and side view of the same creature, scale reference silhouette showing size versus a human figure outline, "
     "close-up panels of skin texture and bioluminescent patterns, color palette swatches, "
     "photorealistic marine megafauna, realistic creature anatomy, clean white background, "
     "no humanoid character, no person, no facial expression sheet, no text labels, "
     "professional creature design sheet layout",
     "humanoid figure, person, human face, anthropomorphic, expression sheet, cartoon, text, gibberish captions"),
    ("sheet", "场景设定图", "生成场景概念设定图时必用（纯画面·禁一切文字）",
     "场景概念图：同一地点的大远景全貌主图+中景细部+多角度小图，按必要性体现人流密度；"
     "必要时只允许无名背景路人、群像或不具角色身份的普通动物，严禁主要人物与主要兽类等核心生物；"
     "纯画面、绝不出现任何文字/标题/标注（旧 concept sheet 措辞会生成 Reef City 标题+乱码段落）",
     # 出图只吃正向词（generate_image 不传 negative）——禁文字 + 禁人物主体 全部写进正向词，
     # 且不用 sheet/thumbnail 等诱发标注的词（否则生成 Reef City 标题+乱码段落 / 前景大头人像）
     "cinematic environment key art of a single location, the place itself is the only subject, "
     "one large aerial extreme-wide establishing shot as the main image, "
     "plus a clearly visible medium eye-level view of the same place and a few alternate angles, "
     "wide landscape framing, "
     "only when necessary for crowd density or scale, anonymous background humans or ordinary non-character animals "
     "may appear as small distant figures "
     "(from empty and desolate to sparse passers-by to a densely packed bustling crowd), "
     "otherwise the environment is completely unoccupied, "
     "no protagonist, no named or recognizable character, no main animal, no main creature, "
     "no dragon, no mount, no monster, no character silhouette, shadow, reflection, statue or mural, "
     "no person in the foreground, no close-up character, no portrait, no face, "
     "consistent lighting and art direction across all views, purely pictorial environment artwork, "
     "absolutely no text, no title, no caption, no label, no annotation, no words, no paragraphs, "
     "no lorem ipsum, no letters, no numbers, no watermark, no signature, no UI frame",
     "characters as main subject, protagonist, named character, recognizable character, "
     "main animal, main creature, dragon, mount, monster, character silhouette, portrait, foreground person, close-up face, "
     "text, title, caption, label, annotation, paragraph, lorem ipsum, gibberish letters, numbers, "
     "watermark, signature, magazine poster layout, artstation sheet with annotations"),
    # ── 质量与负面 ──
    ("quality", "通用质量词", "所有出图默认拼接",
     "分辨率与细节质量兜底词",
     "masterpiece, best quality, highly detailed, sharp focus",
     ""),
    ("quality", "通用负面词", "所有出图默认拼接到 negative",
     "常见畸形与低质量兜底负面词",
     "",
     "lowres, bad anatomy, bad hands, extra fingers, deformed face, blurry, watermark, text, jpeg artifacts"),
]


# ═══════════ 音色库（kind=voice：听觉版设定图，见 docs/arch/voice-timbre-design.md）═══════════
# (name, description=选角检索源, tags, gender, age, emotions)
# 命名用"风格式"（合规红线：不克隆真人声音，参照名只作检索标签）；provider/voice_type 留空待 MVP 绑定
SEED_VOICES: list[tuple[str, str, list[str], str, str, list[str]]] = [
    # ── 男声 · 正面 ──
    ("苍穹卫队长（美国队长式）", "正义、浑厚、领袖感的中年男声；胸腔共鸣饱满，语速沉稳，尾音坚定有力；适合正派领袖、军人统帅、精神支柱型角色",
     ["正义", "浑厚", "男声", "领袖", "中年", "沉稳"], "male", "middle", ["neutral", "solemn", "angry", "encouraging"]),
    ("热血远征少年", "明亮高亢的少年男声；语速偏快，情绪外放，喊招式台词不劈不虚；适合热血主角、冒险少年、运动系角色",
     ["热血", "清亮", "男声", "少年", "激昂"], "male", "young", ["excited", "happy", "angry", "determined"]),
    ("儒雅军师（诸葛式）", "清朗温润的青年男声；吐字讲究、节奏从容，带书卷气的智性感；适合谋士、医师、温和学者型角色",
     ["儒雅", "温润", "男声", "青年", "智性", "从容"], "male", "adult", ["neutral", "gentle", "thoughtful"]),
    ("威严帝王", "低沉庄重的中年男声；共鸣深、字距大、句尾下压，天然的命令感与距离感；适合帝王、家主、最高长官",
     ["威严", "低沉", "男声", "中年", "庄重", "命令感"], "male", "middle", ["solemn", "angry", "cold"]),
    ("慈祥引路长者（甘道夫式）", "苍老而温暖的老年男声；气息绵长，语速缓慢，笑纹感明显，偶有沙哑颗粒；适合导师、老族长、慈祥爷爷",
     ["慈祥", "苍老", "男声", "老年", "温暖", "导师"], "male", "elder", ["gentle", "happy", "solemn", "sad"]),
    ("憨厚山民大叔", "粗粝敦实的中年男声；音色宽厚带土气，语速慢半拍，笑声爽朗；适合忠仆、铁匠、憨直配角",
     ["憨厚", "粗犷", "男声", "中年", "朴实"], "male", "middle", ["happy", "neutral", "worried"]),
    ("悲情孤剑客", "清冷微哑的青年男声；音量收着说话，句尾常带气声消散感，克制的痛感；适合背负血仇的剑客、失意浪人",
     ["悲情", "清冷", "男声", "青年", "沙哑", "克制"], "male", "adult", ["sad", "cold", "neutral", "determined"]),
    ("俏皮机灵小哥", "轻快跳脱的青年男声；语速快、重音俏、爱拖尾音，自带滑稽节奏；适合话痨随从、市集商贩、喜剧担当",
     ["俏皮", "轻快", "男声", "青年", "幽默"], "male", "young", ["happy", "excited", "surprised"]),
    # ── 男声 · 反面 ──
    ("阴鸷军师（高智商反派）", "阴柔平滑的中年男声；音量极稳、语速极慢，笑意藏在句中，礼貌而危险；适合幕后主使、毒士、伪善权臣",
     ["阴鸷", "阴柔", "男声", "反派", "危险", "平滑"], "male", "middle", ["cold", "mocking", "neutral"]),
    ("狂暴屠戮者", "撕裂沙哑的低音男声；喉音重、爆破音狠，怒吼时近破音的压迫感；适合狂战士、暴君打手、兽性反派",
     ["狂暴", "沙哑", "男声", "反派", "凶狠", "低音"], "male", "middle", ["angry", "mocking", "excited"]),
    ("疯批小丑（Joker式）", "忽高忽低的男声；语调不按常理走，突然的假声和低语交替，笑声令人不安；适合疯批反派、癫狂术士",
     ["疯批", "怪诞", "男声", "反派", "不安", "戏剧化"], "male", "adult", ["mocking", "excited", "cold", "unhinged"]),
    ("油滑奸商", "尖细油腻的中年男声；语速快而黏，敬语连珠，转脸即冷；适合势利掌柜、墙头草小官、骗子",
     ["油滑", "尖细", "男声", "小人", "市侩"], "male", "middle", ["happy", "mocking", "worried"]),
    ("冷面督军（低音炮）", "极低沉的金属质感男声；几乎不带情绪起伏，字字如钉；适合冷血指挥官、执法者、大反派麾下督战官",
     ["冷酷", "低音炮", "男声", "反派", "金属感", "无情"], "male", "middle", ["cold", "solemn", "angry"]),
    # ── 女声 · 正面 ──
    ("温柔治愈系姐姐", "轻软温热的青年女声；语速舒缓，句尾上扬带笑，安抚感强；适合治愈系女主、医女、温柔师姐",
     ["温柔", "治愈", "女声", "青年", "轻软"], "female", "adult", ["gentle", "happy", "worried", "sad"]),
    ("飒爽女将军", "利落偏低的青年女声；发声位置靠前，字音干脆无拖沓，命令句斩钉截铁；适合女将、女侠、行动派队长",
     ["飒爽", "利落", "女声", "青年", "英气", "果断"], "female", "adult", ["determined", "angry", "neutral", "encouraging"]),
    ("元气天真少女", "清甜明亮的少女声；语速快、音调高、情绪毫不掩饰，波动大；适合活力少女、小师妹、吉祥物型角色",
     ["元气", "清甜", "女声", "少女", "活泼"], "female", "young", ["happy", "excited", "surprised", "sad"]),
    ("病弱含霜少女", "气声比例高的纤细少女声；音量小、断句短，说几个字就要换气，脆弱易碎感；适合病弱设定、幽闭少女、易碎系角色",
     ["病弱", "纤细", "女声", "少女", "气声", "脆弱"], "female", "young", ["sad", "gentle", "worried"]),
    ("知性大女主", "圆润稳定的中音女声；逻辑重音清晰，不疾不徐，谈判桌气场；适合女企业家、女官、理性大女主",
     ["知性", "沉稳", "女声", "中年", "气场", "理性"], "female", "middle", ["neutral", "solemn", "cold", "encouraging"]),
    ("慈祥外婆", "温软沙糯的老年女声；语速很慢，叠词多，含糊的暖意；适合外婆、老嬷嬷、看护者",
     ["慈祥", "沙糯", "女声", "老年", "温暖"], "female", "elder", ["gentle", "happy", "sad"]),
    ("空灵先知（神谕式）", "飘忽去重力感的女声；混响想象空间大，语句像吟诵，不对任何人说话；适合先知、神使、精灵长老",
     ["空灵", "神秘", "女声", "吟诵", "超然"], "female", "adult", ["neutral", "solemn", "mysterious"]),
    # ── 女声 · 反面 ──
    ("深渊女巫", "阴冷粘稠的中年女声；低音区拖长，齿音尖利，甜腻与狠毒来回切换；适合女巫、毒后、暗黑养母",
     ["阴冷", "凶狠", "女声", "反派", "女巫", "粘稠"], "female", "middle", ["cold", "mocking", "angry", "unhinged"]),
    ("妩媚蛇蝎御姐", "慵懒磁性的低音女声；气声包裹，尾音上挑，每句都像试探；适合双面间谍、魅惑反派、情报贩子",
     ["妩媚", "磁性", "女声", "御姐", "危险", "慵懒"], "female", "adult", ["mocking", "gentle", "cold", "excited"]),
    ("傲娇千金大小姐", "亮而冲的少女声；音调高扬，重音砸在「本小姐」式词上，嘴硬心软的破绽感；适合傲娇大小姐、对手戏女二",
     ["傲娇", "高扬", "女声", "少女", "娇蛮"], "female", "young", ["angry", "happy", "surprised", "sad"]),
    ("疯批玫瑰（Harley式）", "甜美与癫狂并存的女声；上一秒糖分超标下一秒失控大笑，节奏破碎；适合疯批女反派、混乱中立角色",
     ["疯批", "甜美", "女声", "反派", "癫狂", "反差"], "female", "young", ["excited", "mocking", "unhinged", "happy"]),
    ("泼辣市井大婶", "高亢粗嗓的中年女声；音量大、语速快、方言感重，骂人像连珠炮；适合泼辣老板娘、长舌邻居、喜剧配角",
     ["泼辣", "高亢", "女声", "中年", "市井", "喜感"], "female", "middle", ["angry", "happy", "mocking"]),
    # ── 童声 / 特殊 ──
    ("奶气萌娃", "软糯含混的幼童声；咬字不全，语速慢，问句多；适合幼童、团宠、萌物拟人",
     ["奶气", "软糯", "童声", "幼童", "可爱"], "child", "child", ["happy", "sad", "surprised"]),
    ("早熟寡言少年", "变声期前的清冷童声；句子短，音调平，与年龄不符的冷静；适合天才儿童、背负秘密的少年",
     ["早熟", "清冷", "童声", "少年", "寡言"], "child", "young", ["neutral", "cold", "sad"]),
    ("机械AI核心", "均匀无呼吸感的中性合成声；零情绪基线，重要警告时突然拟人；适合飞船AI、机关傀儡、系统旁白",
     ["机械", "中性", "合成", "AI", "无情绪"], "neutral", "none", ["neutral", "alert"]),
    ("远古器灵（咕噜式）", "撕扯沙哑的怪异声线；气声与喉音混杂，自言自语式碎语；适合器灵、地精、洞穴怪物、双重人格",
     ["怪异", "沙哑", "特殊", "生物", "碎语"], "neutral", "elder", ["unhinged", "worried", "mocking"]),
    # ── 动物 / 生物（拟人台词声 + 非语言吼鸣标签；巡夜这类巨兽角色的听觉设定图）──
    ("远古深海巨灵（巡夜式）", "极低频共鸣的巨兽声，似鲸歌与岩层摩擦的混合；拟人台词时低缓如洪钟，非语言时用于长鸣与低吼；适合深海巨兽、上古灵兽、山岳级生物",
     ["巨兽", "低频", "生物", "共鸣", "深海", "威严"], "creature", "elder", ["neutral", "solemn", "roar", "sad"]),
    ("威严龙裔", "金属混响质感的低音兽声；字音间带气焰灼烧的嘶声，句尾余震长；适合巨龙、龙族长老、火系神兽",
     ["龙", "金属感", "生物", "低音", "威严", "混响"], "creature", "elder", ["solemn", "angry", "roar", "mocking"]),
    ("灵狐媚语", "尖俏灵动的雌性兽语；笑音多、转音快，人话与狐鸣无缝切换；适合狐妖、灵狐、狡黠小妖",
     ["狐", "灵动", "生物", "狡黠", "雌性", "妖"], "creature", "young", ["happy", "mocking", "gentle", "excited"]),
    ("忠犬伙伴", "热情粗嗓的拟人犬声；语速快、尾音上扬带喘，兴奋时字句打架；适合忠犬、幼狼、憨萌坐骑",
     ["犬", "热情", "生物", "忠诚", "憨萌"], "creature", "young", ["happy", "excited", "worried", "sad"]),
    ("傲慢猫主子", "慵懒拖腔的猫系声线；鼻音重、句子懒得说完，偶尔的呼噜底噪；适合猫妖、傲娇灵宠、高冷兽伙伴",
     ["猫", "慵懒", "生物", "傲慢", "拖腔"], "creature", "adult", ["neutral", "mocking", "happy", "cold"]),
    ("鸦语者", "嘶哑短促的鸟喉音；句读碎、重复关键词，似鸟鸣卡在人语之间；适合乌鸦信使、鸟灵、不祥预言兽",
     ["鸦", "嘶哑", "生物", "短促", "不祥"], "creature", "elder", ["neutral", "worried", "mocking"]),
    ("巨熊守卫", "瓮声瓮气的浑圆兽声；腔体大、共鸣糊，慢半拍的憨直感；适合巨熊、石像守卫、力量型憨兽",
     ["熊", "瓮声", "生物", "浑厚", "憨直"], "creature", "middle", ["neutral", "happy", "angry", "roar"]),
    ("虫群意识", "多声部叠影的耳语群声；主声之下有无数细碎跟读，方向感模糊；适合虫群主脑、菌群意识、群体生物",
     ["虫群", "多声部", "生物", "耳语", "诡异"], "creature", "none", ["neutral", "cold", "unhinged"]),
    ("温顺草食巨兽", "绵长低哞般的憨厚兽声；气息悠长，音色圆钝无攻击性；适合巨型坐骑、田园灵兽、温柔巨物",
     ["草食", "低哞", "生物", "温顺", "绵长"], "creature", "middle", ["neutral", "gentle", "happy", "sad"]),
    ("幼兽咿呀", "动物幼崽的咿呀拟声；音高不稳带颤，词不成句但情绪直白；适合幼龙、幼兽、蛋生萌宠",
     ["幼兽", "咿呀", "生物", "软萌", "颤音"], "creature", "child", ["happy", "sad", "surprised", "worried"]),
    # ── 旁白 ──
    ("磁性纪录片旁白（男）", "醇厚磁性的中年男声；气息深、断句讲究，抽离而不冷漠；适合正片旁白、章节引言、预告",
     ["旁白", "磁性", "男声", "醇厚", "叙述"], "male", "middle", ["neutral", "solemn"]),
    ("知性电台旁白（女）", "松弛透明的青年女声；音量小而近，耳语般的亲密叙述感；适合情感线旁白、回忆独白、治愈系正片",
     ["旁白", "知性", "女声", "松弛", "亲密"], "female", "adult", ["neutral", "gentle", "sad"]),
]


# ═══════════ 人物特征库（kind=prompt_block, category=persona：年龄段多维画像）═══════════
# 正文按维度分行（「维度名：内容」），消费方经 services/persona_traits.py **按维度渐进检索**：
# ① 捏音色/情绪小样：只取 声音特征+言语风格；② 角色外貌补档：只取 体态特征+发量特征；
# ③ 分镜动作（预留）：只取 动作特征。绝不整条目全量拼进提示词。
# meta.params 同时是该年龄段的韵律兜底：音色未标 params.speed 时按 age 取默认基线（见 prosody.age_base_speed）。
# (name, description=何时召回, content=多维正文, meta)
PERSONA_TRAITS: list[tuple[str, str, str, dict]] = [
    ("幼童", "幼龄角色（3-8岁）的声线/语域/体貌/动作画像",
     "声音特征：软糯含混，音高偏高，咬字不全，语速偏慢，句子很短，气息浅。\n"
     "言语风格：叠词多（吃饭饭/怕怕）、问句多、词汇简单直白，不会用成语和长句。\n"
     "体态特征：头身比大（四到五头身），四肢短圆，肚子微凸，站姿不稳重心晃。\n"
     "发量特征：胎发细软蓬松，发量中等，发际线低而圆。\n"
     "动作特征：动作大而不精准，爱蹦跳，跑动重心前倾，抓握用整个手掌。",
     {"age": "child", "age_range": [1, 8], "params": {"pitch": "high", "speed": "slow", "energy": "soft"}}),
    ("少年", "少年男性角色（9-17岁）的声线/语域/体貌/动作画像",
     "声音特征：清亮偏高（变声期前后），语速偏快，情绪外放，尾音上扬，音量控制不稳。\n"
     "言语风格：直来直去、感叹句多、口语化，爱用短句抢话，不打官腔。\n"
     "体态特征：身形抽条清瘦，肩窄骨架未张开，六到七头身，站坐难安分。\n"
     "发量特征：发量浓密蓬乱，发质硬挺有光泽，发际线饱满。\n"
     "动作特征：动作快而冲，跑跳利落，手势幅度大，习惯性挠头、插兜。",
     {"age": "young", "gender": "male", "age_range": [9, 17], "params": {"pitch": "high", "speed": "fast", "energy": "mid"}}),
    ("少女", "少女角色（9-17岁）的声线/语域/体貌/动作画像",
     "声音特征：清甜明亮，音调高，语速轻快，情绪波动大，笑音与气声多。\n"
     "言语风格：语气词多（呀/啦/嘛/诶）、活泼直白、疑问和感叹交替，句子短而跳。\n"
     "体态特征：身形纤细初显曲线，肩薄颈长，六到七头身，体态轻盈。\n"
     "发量特征：发量浓密顺滑有光泽，发际线圆润，常见编发、双马尾等少女发式。\n"
     "动作特征：动作轻快带弹性，爱转身、踮脚、摆手，小动作多（拨头发/绞衣角）。",
     {"age": "young", "gender": "female", "age_range": [9, 17], "params": {"pitch": "high", "speed": "fast", "energy": "mid"}}),
    ("青年", "青年角色（18-35岁）的声线/语域/体貌/动作画像",
     "声音特征：清朗或圆润有弹性，气息足，语速适中，吐字清晰，情绪收放自如。\n"
     "言语风格：利落完整的现代语感，逻辑清楚，语气词少，按身份可书卷可市井。\n"
     "体态特征：体格定型，肩背舒展挺拔，七到八头身，肌肉线条紧实。\n"
     "发量特征：发量最盛，发质健康浓密，发际线完整。\n"
     "动作特征：动作干脆有力，步幅大而稳，手势精准，反应敏捷。",
     {"age": "adult", "age_range": [18, 35], "params": {"pitch": "mid", "speed": "mid", "energy": "mid"}}),
    ("中年", "中年角色（36-55岁）的声线/语域/体貌/动作画像",
     "声音特征：音色厚实沉稳，共鸣足，语速稍缓，重音清晰，句尾下压有分量。\n"
     "言语风格：用词稳重、句式完整、少语气词，习惯先结论后解释，官腔或家长腔按身份。\n"
     "体态特征：体型敦实微发福或干练精瘦（按身份），肩背厚重，站姿沉稳压场。\n"
     "发量特征：发量开始稀疏，发际线后移或额角微秃，鬓角初见霜色。\n"
     "动作特征：动作从容不赶，步态沉稳，手势少而有分量，习惯负手、抱臂。",
     {"age": "middle", "age_range": [36, 55], "params": {"pitch": "low", "speed": "mid", "energy": "mid"}}),
    ("老者", "老年角色（55岁以上）的声线/语域/体貌/动作画像",
     "声音特征：沧桑苍老，沙哑带颗粒感，气息偏短，语速缓慢，停顿多，音量偏低。\n"
     "言语风格：老派用词，多短叹（唉/罢了/也罢），称谓庄重，爱引旧事与训诫，句子不急不抢。\n"
     "体态特征：背脊佝偻或清瘦嶙峋，肩塌颈前伸，关节粗大，皮肤松弛见寿斑。\n"
     "发量特征：发量稀疏花白或全白，发际线大幅后移或秃顶，眉须皆白。\n"
     "动作特征：动作迟缓幅度小，步态碎而慢，手微颤，起身常拄杖或扶物。",
     {"age": "elder", "age_range": [56, 120], "params": {"pitch": "low", "speed": "slow", "energy": "soft"}}),
]


# ═══════════ 要素类型库（kind=element_type：项目要素的分组类型）═══════════
# 大纲就绪后由 gen_element_kinds 任务把整份清单喂给 LLM，按剧情判定本项目需要哪些类型
# （写入项目 config.element_kinds）。(code, name, desc, content, core)：
# core=基础类型（任何故事都需要，判定时强制保留）；content=类型说明+适用判据（LLM 取舍依据）
ELEMENT_TYPES: list[tuple[str, str, str, str, bool]] = [
    ("character", "角色", "登场人物（含拟人化生物/器灵）",
     "有名有姓、推动剧情的登场角色（含拟人化动物、器灵）。需外貌提示词出设定图、按发声形态捏音色。任何故事都需要。", True),
    ("scene", "场景", "关键剧情发生的地点/空间",
     "反复出现或承载关键剧情的地点（宗门大殿/雨夜码头/飞船舰桥）。需概念图锚定视觉一致性。任何故事都需要。", True),
    ("plotline", "剧情线", "跨章推进的主线/支线/阴谋线",
     "跨多章推进、需要跟踪进度的剧情线索（主线/支线/阴谋线）。多线叙事、群像、悬疑阴谋类必备；单线短篇可省。", False),
    ("conflict", "冲突线", "人物/势力间的持续对立",
     "贯穿多章的核心矛盾与对立关系（正邪之争/夺嫡/商战/情感拉扯）。强对抗类剧情必备。", False),
    ("foreshadow", "伏笔", "铺设与回收的钩子",
     "跨章铺设、后文回收的伏笔点（身世之谜/神秘物件/一句谶语）。悬疑向与长篇必备；直给型短篇可省。", False),
    ("setting", "设定", "世界观规则/体系",
     "力量体系、修炼等级、科技树、社会规则等抽象世界观设定。幻想/科幻/仙侠类必备；现实题材通常可省。", False),
    ("faction", "组织势力", "门派/家族/公司/阵营",
     "有立场与目标的组织势力（宗门/世家/公司/军团/帮派）。群像、权谋、多阵营对抗类适用。", False),
    ("item", "关键道具", "法宝/信物/麦高芬",
     "推动剧情的关键实物（法宝/遗物/信物/黑科技装置），多数有视觉形态需要设定图。寻宝、金手指、信物驱动类适用。", False),
]


# ═══════════ 数字员工技能（kind=skill：员工的"how"，装配期与章程/知识块合成系统提示词）═══════════
# (agent_code, name, description, content) —— content 为空则延迟从代码常量取（单一来源防漂移）
def _seed_skills() -> list[tuple[str, str, str, str]]:
    from .services.scene_blocking import BLOCKING_RULES
    from .services.storyboard import (
        _STORYBOARD_COARSE_FORMAT, _STORYBOARD_DETAIL_FORMAT, _STORYBOARD_FORMAT,
        DIRECTOR_RULES, IMAGE_REVIEW_RULES, VIDEO_REVIEW_RULES,
    )
    from .services.voice_casting import VOICE_DESIGN_RULES

    return [
        ("reviewer", "视频提示词质检", "视频提示词质检时装配的评审规则正文（十三维，含站位连贯；输出 JSON 契约由代码强制追加）",
         VIDEO_REVIEW_RULES),
        ("reviewer", "首帧提示词质检", "首帧提示词质检时装配的评审规则正文（十维，含站位一致；输出 JSON 契约由代码强制追加）",
         IMAGE_REVIEW_RULES),
        # 导演输出格式段（红线：枚举取值与 JSON 字段名是校验 Gate 的依据，改动前务必对齐后端枚举）
        ("director", "分镜输出格式", "单轮完整拆镜的输出格式段（枚举+JSON schema；改动需对齐后端校验枚举）",
         _STORYBOARD_FORMAT),
        ("director", "粗拆骨架输出格式", "两阶段拆镜第一轮：只拆骨架的输出格式段（改动需对齐后端校验枚举）",
         _STORYBOARD_COARSE_FORMAT),
        ("director", "详细分镜输出格式", "两阶段拆镜第二轮：逐镜补镜头语言的输出格式段（含 cuts 运镜叙事词汇表；改动需对齐后端校验枚举）",
         _STORYBOARD_DETAIL_FORMAT),
        ("voice", "捏音色", "为角色设计/绑定专属音色时装配；指令优先→性格自主→库复用→三层描述→参数三档",
         VOICE_DESIGN_RULES),
        ("director", "专业分镜拆解", "章节→分镜序列时装配；含每镜一问/单动作/时长曲线/景别角度焦段光效十条铁律",
         DIRECTOR_RULES),
        ("director", "场景空间规划", "场景组空间规划（blocking）时装配；空间布局+逐镜站位链+单幅场景空间站位图描述——跨镜空间连贯的锚",
         BLOCKING_RULES),
        ("writer", "长篇章节写作", "写分集正文时装配；剧集写法（对白驱动/进场晚退场早/展示而非叙述）+检索纪律+回写三件",
         "你为「影视漫剧/短剧」写分集正文，写的是对白与画面驱动的场景化叙事，不是小说散文。铁律："
         "1.进场晚退场早：每场戏从冲突或关键信息切入，砍掉进门/寒暄/铺垫；转折点一到立刻收，不交代「后来」。"
         "2.每场必翻面：一场戏首尾人物处境或情绪必须变化（安全→危险、信任→怀疑）；首尾不变的场景删掉。"
         "3.对白驱动占主体：剧情主要靠人物对话和动作推进，对白是叙述的主干而非点缀。"
         "4.潜台词：人物不直说心里话，戏藏在「说出口的」和「真想的」落差里；禁止把动机情绪直接说白。"
         "5.展示而非叙述：不写「他很愤怒/她很害怕」，改写成可被画出来的动作、表情、物件细节。"
         "6.环境压到一两句：场景描写只留承载信息或情绪的那一两笔，其余交给分镜作画，不做感官大铺陈。"
         "7.欲望推进：每场交代人物此刻要什么、什么挡路，靠「要—受阻—再要」，不靠旁白解释动机。"
         "8.视觉化交代设定：世界观/身份/关系尽量用台词或画面里看得见的东西透出，不用上帝视角叙述倒叙。"
         "9.留白有节奏：高压戏后给一个短促静默落点（一个动作/一样物/一句短叹），但留白仅一两句，不注水。"
         "10.短段推进：段落短、切换干净；禁止用大段叙述填充篇幅。"
         "严格衔接「最近章节流水账」不得与已有事实矛盾；只能使用「本章要素」中的角色/场景并遵守其当前状态；"
         "按「本章故事线」推进剧情并落实伏笔标注；写完必须输出本章流水账与要素状态变化（回写三件是检索之源）。"),
        ("artist", "分镜提示词装配", "为分镜出图/出视频装配提示词时参照；两段式+身份层+Seedance 二十法纪律",
         "装配纪律：两段式生成——彩色首帧含全部静态信息（画面/动作瞬间/景别/角度/焦段/光效/色调/画风块/身份层），"
         "视频提示词只写运动增量且主体动作永远前置；身份层（角色外貌提示词）每镜必注入不省略；"
         "本镜关联要素的设定图必须作为参考图传递（角色/场景一致性锚点）；负面词兜底必拼。\n"
         "Seedance 写词纪律（官方二十法沉淀）：主体精准定义（核心属性+外观+状态，禁模糊表述）；"
         "动作写时序（先后顺序+速度+幅度，避免单点动作）；光影具象（光线类型+明暗效果，禁'氛围感拉满'类空话）；"
         "禁'好看/高级/有感觉'等抽象词，一律替换为具体描述；风格词单条最多1-2个不混杂；"
         "单镜运镜最多2种不堆砌；有参考图时必加'与参考图主体完全一致，不修改核心设定'；"
         "中文写意境，英文只留镜头/画质术语锚词。"),
        ("voice", "配音方案设计", "为分镜台词/旁白设计配音时装配",
         "配音方法：按角色卡的年龄/性格分配声线；台词情绪跟随本镜 mood 字段；旁白克制，不与画面信息重复。"),
    ]


async def seed_knowledge(pool: asyncpg.Pool) -> int:
    """幂等 seed：按 (scope,kind,category,name) 不存在才插。返回新插条数。"""
    inserted = 0
    async with pool.acquire() as conn:
        for category, name, desc, content, positive, negative in SEED_BLOCKS:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='prompt_block' "
                "AND category=$1 AND name=$2",
                category, name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, meta) "
                "VALUES ('global', 'prompt_block', $1, $2, $3, $4, $5::jsonb)",
                category, name, desc, content,
                json.dumps({"positive": positive, "negative": negative}, ensure_ascii=False),
            )
            inserted += 1
        # 音色库 seed（kind=voice：听觉版设定图；provider/voice_type 留空待 MVP 绑定火山音色）
        from .services.voice_casting import _age_tag

        for name, desc, tags, gender, age, emotions in SEED_VOICES:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='voice' AND name=$1", name,
            )
            if row:
                continue
            atag = _age_tag(age, gender)  # 年龄标签兜底（与捏音色/存量补标同一映射）
            if atag and atag not in tags:
                tags = tags + [atag]
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, tags, meta) "
                "VALUES ('global', 'voice', 'timbre', $1, $2, $3, $4, $5::jsonb)",
                name, desc, desc, tags,
                json.dumps({
                    "provider": None, "voice_type": None, "ref_audio_url": None,
                    "sample_audio_url": None, "image_url": None,
                    "gender": gender, "age": age, "emotions": emotions,
                }, ensure_ascii=False),
            )
            inserted += 1
        # 人物特征库 seed（kind=prompt_block, category=persona：年龄段声线/语域画像）
        for name, desc, content, meta in PERSONA_TRAITS:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='prompt_block' "
                "AND category='persona' AND name=$1", name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, meta) "
                "VALUES ('global', 'prompt_block', 'persona', $1, $2, $3, $4::jsonb)",
                name, desc, content, json.dumps(meta, ensure_ascii=False),
            )
            inserted += 1
        # 全局技能：没有才新建（用户 2026-07-13 定稿：重启不覆盖——管理页改的内容是权威版本，
        # 代码常量只作首次初始化与装配兜底；代码侧升级技能内容需在管理页手动同步或删条目重启重建）
        for agent_code, name, desc, content in _seed_skills():
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='skill' "
                "AND agent_code=$1 AND name=$2",
                agent_code, name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, agent_code) "
                "VALUES ('global', 'skill', $1, $2, $3, $4, $1)",
                agent_code, name, desc, content,
            )
            inserted += 1
        # Seedance 视频方法论（kind=knowledge：管理员查阅 + AI 编辑提示词参照，不进 recall_blocks）
        # 与全库策略一致：没有才新建，重启不覆盖
        for name, desc, content in SEEDANCE_METHODS:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='knowledge' "
                "AND category='video_method' AND name=$1", name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content) "
                "VALUES ('global','knowledge','video_method',$1,$2,$3)",
                name, desc, content,
            )
            inserted += 1
        # 文风库（引导式新建选择用；kind=knowledge 与 cocc 迁移的"金庸武侠"同类）
        for name, desc, content in WRITING_STYLES:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='knowledge' "
                "AND category='writing_style' AND name=$1", name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content) "
                "VALUES ('global','knowledge','writing_style',$1,$2,$3)",
                name, desc, content,
            )
            inserted += 1
        # 要素类型库（kind=element_type：gen_element_kinds 按剧情从中判定项目要素分组）
        for code, name, desc, content, core in ELEMENT_TYPES:
            row = await conn.fetchrow(
                "SELECT id FROM kb_entries WHERE scope='global' AND kind='element_type' AND name=$1",
                name,
            )
            if row:
                continue
            await conn.execute(
                "INSERT INTO kb_entries (scope, kind, category, name, description, content, meta) "
                "VALUES ('global','element_type','element',$1,$2,$3,$4::jsonb)",
                name, desc, content,
                json.dumps({"code": code, "core": core}, ensure_ascii=False),
            )
            inserted += 1
        # 内容类型路由：视频生产相关技能与知识显式打上视频类型标签。
        # 这一步放在 seed 之后执行，既覆盖存量条目，也能覆盖重启时新补入的条目。
        video_tags = ["brand_ad", "film_drama", "big_screen", "geo_promo", "product_ad"]
        await conn.execute(
            "UPDATE kb_entries SET tags=$1 "
            "WHERE enabled AND ((kind='knowledge' AND category='video_method') "
            "OR (kind='skill' AND agent_code IN ('reviewer','director','artist','voice'))) "
            "AND (tags IS NULL OR tags='{}')", video_tags)
        await conn.execute(
            "UPDATE skill_packages s SET tags=e.tags "
            "FROM kb_entries e WHERE e.id=s.legacy_kb_id "
            "AND (s.tags IS NULL OR s.tags='{}') AND e.tags<>'{}'")
    return inserted


# Seedance 视频生成方法论（kind=knowledge, category=video_method）：
# 来源=火山引擎官方学习资料（20 提示词法+40 运镜法）与案例库沉淀，供管理员查阅与 AI 编辑提示词时参照
SEEDANCE_METHODS: list[tuple[str, str, str]] = [
    ("Seedance提示词二十法精要", "写/改视频提示词时参照的方法论（火山官方推荐）",
     "基础八法：①主体精准定义（核心属性+外观特征+状态，拒绝模糊表述）②时序动作（写清动作先后顺序/速度/幅度，"
     "避免单点动作）③景运组合（每句1景别+1运镜不堆砌；安全组合=近景+慢推/中景+跟拍/全景+慢拉）"
     "④光影具象（光线类型+明暗效果，禁'氛围感拉满'类空话）⑤画质句兜底（4K超高清/细节丰富/无噪点/无模糊）"
     "⑥风格单一（单条只用1-2个风格词）⑦图生视频必加'与参考图主体完全一致，不修改核心设定'"
     "⑧负面词精简（无变脸/无肢体畸形/无穿模/无跳帧）。\n"
     "进阶八法：⑨权重标注{1.0-1.5}核心主体优先 ⑩动作幅度速度修饰 ⑪场景氛围具象（时间+环境+细节）"
     "⑫中英混写（中文写意境，英文写镜头/画质术语）⑬多镜头分镜（镜号+景别+运镜+动作）"
     "⑭强制约束（面部清晰无畸变/五官比例自然/同一角色服装全程一致）⑮节奏控制（慢动作定格3秒再匀速恢复）"
     "⑯素材联动（@图片N提取造型/@视频N提取动作节奏）。\n"
     "避坑四法：⑰单条最多2种运镜 ⑱不混杂多种风格 ⑲动作优先缓慢匀速提升稳定性 ⑳删除'好看/高级/有感觉'等抽象词，"
     "全部替换为具体描述。"),
    ("Seedance运镜四十法精要", "分镜设计与视频提示词写运镜时参照（火山官方推荐）",
     "基础十式（覆盖80%场景）：慢推（突出细节）/慢拉（开阔感）/横摇（扫视场景）/竖摇（揭晓高度）/"
     "环绕（立体展示）/跟拍（沉浸代入）/固定（对话纪实）/微距（纹理细节）/定格3秒（核心瞬间）/手持微抖（纪实感）。\n"
     "组合二十式精选：推拉结合（悬念揭示）/跟拍+环绕（自然切换视角）/升降+横摇（模拟航拍）/环绕+慢推（增强张力）/"
     "慢推+定格（强化记忆点）/固定+快切（卡点节奏）/跟拍+慢拉（主体与环境关系）/定格+慢拉（收尾疏离感）/"
     "微距+环绕（全方位细节）/慢推+竖摇（细节+高度）。\n"
     "专业十式（电影级）：希区柯克变焦（主体不变背景压缩，时空扭曲感）/一镜到底（沉浸漫游）/荷兰角（不安悬疑）/"
     "升格慢动作（关键瞬间仪式感）/匹配剪辑转场 Match Cut（无缝时空跳跃）/高速螺旋环绕（能量爆发）/"
     "俯冲运镜（紧张冲击）/快速拉升（揭晓全景）/摇镜快切（动感节奏）/焦外虚化缓移（氛围突出主体）。\n"
     "纪律：单镜最多2种运镜；运镜指令写在时间轴段首标注内，不写孤立参数行。"),
]


# 文风库 seed：(name, description=何时适用, content=可执行写作风格指令——直接作为项目 writing_style)
WRITING_STYLES: list[tuple[str, str, str]] = [
    ("莫言乡土魔幻", "文风=乡土/家族史诗/魔幻现实",
     "莫言式乡土魔幻：长句铺排，感官轰炸，泥土与血性的意象密集堆叠，人畜草木皆有灵，"
     "叙述在残酷与狂欢间摇摆，方言口语入文。"),
    ("冷峻悬疑", "文风=悬疑/犯罪/惊悚",
     "冷峻悬疑：短句冷硬，信息克制，多用白描与留白，延迟揭示关键事实，"
     "以环境细节堆积不安感，对白惜字如金。"),
    ("古风仙侠", "文风=仙侠/古典玄幻/修真",
     "古风仙侠：雅致凝练，意象空灵，山川器物皆入典，动静之间见境界，"
     "对白半文半白，打斗写意不写实。"),
    ("都市轻快", "文风=都市/职场/恋爱轻喜剧",
     "都市轻快：口语化叙述，节奏明快，梗密度高，心理吐槽与对白交错，"
     "章末留钩子，情绪轻盈不下沉。"),
    ("热血爽文", "文风=升级流/逆袭/爽文",
     "热血爽文：强目标驱动，冲突前置，压抑-爆发的打脸节奏，爽点密集，"
     "战斗描写动词强劲，配角反应烘托主角高光。"),
    ("克制现实主义", "文风=现实题材/文艺/情感正剧",
     "克制现实主义：平实精准的白描，情绪藏在动作与物件里，少形容词，"
     "对白贴生活肌理，重要时刻反而收着写。"),
    # ↓ 剧集气质定位（影视漫剧）：决定分集正文的整体腔调，配合 writer 剧集写法铁律使用
    ("皮克斯式情感内核", "影视漫剧气质=温暖成长/情感驱动",
     "皮克斯式情感内核：轻快明亮，每集一个清晰情感目标，温暖幽默里藏成长，"
     "冲突服务于人物的「想要 vs 需要」，结尾落在情感转变上。"),
    ("漫威式高节奏爽感", "影视漫剧气质=商业快节奏/爽感钩子",
     "漫威式高节奏爽感：快节奏，对白带机锋和幽默quip，动作与情绪同拍推进，"
     "每场埋钩子，爽点密集，绝不拖泥带水。"),
    ("宫崎骏式留白日常", "影视漫剧气质=克制留白/日常抒情",
     "宫崎骏式留白日常：克制安静，情绪靠环境细节与静默呈现，日常里藏情感，"
     "不把话说满，节奏有呼吸，高压后必有一个静默落点。"),
    ("冷硬悬疑速写", "影视漫剧气质=悬疑冷调/信息克制",
     "冷硬悬疑速写：短句短场，信息克制，对白全是潜台词，靠画面透露而非解释，"
     "延迟揭示关键事实，冷调张力。"),
    ("热血少年爽剧", "影视漫剧气质=热血升级/强对抗",
     "热血少年爽剧：强目标强对抗，台词直给有燃点，场场升级不拖沓，"
     "反转快、钩子狠，配角反应烘托主角高光。"),
]
