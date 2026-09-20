-- 场景光影站位锚定（2026-07-28）：标准 agentskills.io Skill + 数字员工绑定。
--
-- 起因：场景锚定图此前让模型在一张图里自己画多个视角。先是写死"两个视角"，实测两格
-- 各画各的；改成让模型自选宫格（默认三格：空场景/俯视平面/角色站位）后再测（章1026
-- 场景1），依然不行——空场景格里站着人、俯视格画成了场景设定图的翻版、同一条龙在两格
-- 里完全两个样。根因是格与格之间除了文字没有任何硬锚，模型对第二格只能重新想象一遍。
--
-- 定稿改两阶段：先出**无人空场景基准图**把几何与光钉死，再把这张成图**当参考图**去出
-- 角色站位图。空间从此有实物锚，模型只需在给定空间里摆人。
INSERT INTO skill_packages(
    slug,name,description,version,source_url,license,skill_md,manifest,status
) VALUES (
    'scene-light-blocking-anchor',
    '场景光影站位锚定',
    '两阶段锚定一个场景组的空间与光影：先出无人空场景基准图钉死几何与光，再以它为参考图出角色站位图；组内所有镜头以基准图为空间真值。',
    '2.0.0',
    'repo://skills/scene-light-blocking-anchor',
    'MIT',
    $$---
name: scene-light-blocking-anchor
description: Lock a scene group's geometry, lighting and character blocking with a two-stage anchor. Use when planning a scene group's spatial layout, writing the empty-plate or blocking-sheet prompt, deciding what goes in each stage's reference pool, keeping furniture/camera/key-light identical between the two images, or preventing characters from appearing in the empty plate.
---

# 场景光影站位锚定（两阶段）

一个场景组出两张单幅图，组内每个镜头都以它们为空间与光影真值。

## 第一阶段·空场景基准图

**画面里不得出现任何人物或生物。** 一个机位、一种景别的完整单幅画面，交代空间轮廓、
关键结构物方位、家具陈设、材质，以及时间段、天气、主光方向、光质、环境光色、明暗层次
与阴影落向。

这一张是整个场景组的几何与光的真值。被人物挡住的空间就不再是真值——所以它必须先出、
必须无人。**参考池只放项目环境锚点与场景设定图，一张角色设定图都不能放**：放了模型
就会把人画进来。

## 第二阶段·角色站位图

**以第一阶段的成图作参考图生成。** 空间结构、建筑与家具陈设、材质、机位角度、景别、
镜头朝向、时间天气、主光方向与明暗层次**全部照搬基准图，一律不得改动、不得换机位、
不得增删结构物**；本阶段唯一新增的内容是按站位锚把角色放进这个空间里。

描述只写"谁站在哪、相互距离多远、朝向何方"，不重新描述空间、机位、景别或光线。

## 共同纪律

1. 两张是同一场景、同一时刻、同一天气、同一主光方向下的同一个机位。
2. 角色造型以其设定图为准，不得增减人数、不得换脸换装；没有设定图的角色按文字描述，
   并写清体型与关键特征。
3. 角色面部不是表现重点，避免五官正面特写与直视镜头（此图作参考图提交视频模型，
   写实正面人脸会触发"疑似真人"审核拒收，整镜视频白跑）。
4. 两张都是满幅单幅画面。禁止：宫格、拼图、分镜板、接触表、分割线、画中画、相框白边、
   同一画面的重复变体；画面内任何文字、字幕、编号、标注与水印。

## 出了问题先修哪一张

基准图错了而只重出站位图，等于在错的空间里反复摆人。**永远先修基准图。**

逐项检查见 references/stage-checklist.md，光影字段写法见 references/lighting-anchor.md。
$$,
    '{"format":"agentskills.io","local_path":"skills/scene-light-blocking-anchor","category":"scene-continuity"}'::jsonb,
    'installed'
)
ON CONFLICT(slug) DO UPDATE SET
    name=excluded.name,description=excluded.description,version=excluded.version,
    source_url=excluded.source_url,license=excluded.license,skill_md=excluded.skill_md,
    manifest=excluded.manifest,status='installed',updated_at=now();

INSERT INTO skill_package_files(skill_id,path,content)
SELECT id,'references/stage-checklist.md',$$两阶段产物检查表：

**第一阶段·空场景基准图（必须先出）**

| 检查项 | 通过标准 | 不通过的后果 |
|---|---|---|
| 画面内有人吗 | 一个人、一只动物、一道人影都没有 | 站位图会照抄这个人，等于凭空多出角色 |
| 空间读得懂吗 | 墙/门/窗/主要家具的相对方位一眼可辨 | 组内各镜的空间各画各的 |
| 光源交代了吗 | 时间段、天气、主光方向、阴影落向都在画面上成立 | 每镜光线自由漂移 |
| 是单幅吗 | 无宫格、无分割线、无相框白边 | 下游把分格当成画面内容 |
| 机位可复用吗 | 一个机位、一种景别，不是拼贴 | 站位图无从照搬 |

参考池只放：项目环境锚点、场景设定图。**一张角色设定图都不能放**——放了就会画出人。

**第二阶段·角色站位图**

| 检查项 | 通过标准 |
|---|---|
| 空间是否照搬 | 墙、门、窗、家具的位置与数量和基准图逐一对得上 |
| 机位是否照搬 | 景别、机位角度、镜头朝向与基准图一致 |
| 光线是否照搬 | 主光方向与阴影落向和基准图一致 |
| 人数是否正确 | 与 anchors 的角色数完全相同，不多不少 |
| 造型是否受锚 | 每个角色都能对上自己的设定图；没有设定图的角色要在文字里写清体型与关键特征 |

参考池第一位固定是本场景的空场景基准图，其后是出场角色的设定图。

**两阶段都不通过时的处置**：先修基准图再重出站位图。基准图错了而只重出站位图，
等于在错的空间里反复摆人。
$$
FROM skill_packages WHERE slug='scene-light-blocking-anchor'
ON CONFLICT(skill_id,path) DO UPDATE SET content=excluded.content;

INSERT INTO skill_package_files(skill_id,path,content)
SELECT id,'references/lighting-anchor.md',$$光影锚定字段（在空场景基准图上一次钉死，站位图照搬）：

| 字段 | 必填 | 写法 | 反例 |
|---|---|---|---|
| 时间段 | 是 | 黄昏日落前半小时 | 傍晚时分（不可判断太阳高度） |
| 天气 | 是 | 晴，薄云，能见度高 | 天气不错 |
| 主光方向 | 是 | 主光自西侧窗户斜射入室，光轴由画面右后方指向左前方 | 侧光 |
| 光质 | 是 | 硬光，边缘清晰的窗格投影 | 光线很美 |
| 环境光色 | 是 | 暖橙为主，阴影区受冷蓝天光补光 | 暖色调 |
| 明暗层次 | 是 | 窗边高光、工作台中间调、屋角深暗，明暗比约 4:1 | 明暗对比强 |
| 阴影落向 | 是 | 家具投影统一朝画面左前方拉长 | 有影子 |

人工光源（灯、火、屏幕）必须在基准图里就出现并标明位置；站位图不得凭空多出新光源，
也不得因为加了角色就改变主光方向。

室内场景额外锁：屋顶完整、不得露出天空；窗外景物在两张中保持同一内容与同一亮度。
$$
FROM skill_packages WHERE slug='scene-light-blocking-anchor'
ON CONFLICT(skill_id,path) DO UPDATE SET content=excluded.content;

-- 版式改两阶段后作废：宫格选型表不再适用（实测多宫格治不了跨格漂移）
DELETE FROM skill_package_files f USING skill_packages s
WHERE f.skill_id=s.id AND s.slug='scene-light-blocking-anchor'
  AND f.path='references/panel-layouts.md';

-- 绑定到场景设计师（主）与连续性主管（跨镜一致性把关）
INSERT INTO agent_template_skills(agent_template_id,skill_id)
SELECT a.id,s.id FROM agent_templates a CROSS JOIN skill_packages s
WHERE a.code IN ('scene-designer','continuity-supervisor')
  AND s.slug='scene-light-blocking-anchor'
ON CONFLICT DO NOTHING;

INSERT INTO agent_skill_bindings(agent_id,skill_id)
SELECT a.id,s.id FROM agents a CROSS JOIN skill_packages s
WHERE a.code IN ('scene-designer','continuity-supervisor')
  AND s.slug='scene-light-blocking-anchor'
ON CONFLICT DO NOTHING;
