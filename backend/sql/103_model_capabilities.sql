-- 103: 模型能力档案落库（2026-09-17）
-- 「模型=数据」：把各视觉模型的协议/参考图上限/比例支持声明进模型档，
-- 服务端在 provider 边界按档案裁剪请求，前端画布按档案自适应。
-- 全部是幂等 UPDATE（extra 只增不覆盖 capabilities 外的键）。

-- dashscope 图像编辑族：同步多模态接口，1~3 张底图，比例跟随参考图
UPDATE model_profiles SET max_refs = 3, extra = jsonb_set(
    COALESCE(extra, '{}'::jsonb), '{capabilities}',
    '{"transport":"sync","refs":{"max":3,"kind":"edit_base"}}'::jsonb, true)
WHERE provider='dashscope' AND model_name LIKE 'qwen-image-edit%';

-- dashscope 文生图族：异步任务协议，纯文生图不吃参考图
UPDATE model_profiles SET max_refs = 0, extra = jsonb_set(
    COALESCE(extra, '{}'::jsonb), '{capabilities}',
    COALESCE(extra->'capabilities', '{}'::jsonb) ||
    '{"transport":"async","refs":{"max":0,"kind":"none"}}'::jsonb, true)
WHERE provider='dashscope' AND model_name IN ('qwen-image', 'wanx-v1')
   OR (provider='dashscope' AND model_name LIKE 'wan2.%-image');

-- 火山 seedream 4.x：支持 4 张参考图
UPDATE model_profiles SET max_refs = 4, extra = jsonb_set(
    COALESCE(extra, '{}'::jsonb), '{capabilities}',
    COALESCE(extra->'capabilities', '{}'::jsonb) ||
    '{"refs":{"max":4,"kind":"reference"}}'::jsonb, true)
WHERE provider='ark' AND model_name LIKE '%seedream-4%';

-- minimax：subject_reference 单槽
UPDATE model_profiles SET max_refs = 1, extra = jsonb_set(
    COALESCE(extra, '{}'::jsonb), '{capabilities}',
    COALESCE(extra->'capabilities', '{}'::jsonb) ||
    '{"refs":{"max":1,"kind":"subject"},"aspects":["1:1","16:9","9:16","4:3","3:4","21:9"]}'::jsonb, true)
WHERE provider='minimax' AND purpose='image';

-- grsai：nano-banana 走自有 REST，size 不支持
UPDATE model_profiles SET max_refs = 0, extra = jsonb_set(
    COALESCE(extra, '{}'::jsonb), '{capabilities}',
    COALESCE(extra->'capabilities', '{}'::jsonb) ||
    '{"refs":{"max":0,"kind":"none"}}'::jsonb, true)
WHERE provider='grsai' AND purpose='image';
