-- 1) 运行上下文落库：ctx 原来只活在解释器的内存里，运行一结束就没了。
--    AI 智能规划要拿「这一轮各节点的入参/出参」当历史对话，就得有一份可回读的轨迹。
ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS context jsonb NOT NULL DEFAULT '[]'::jsonb;

-- 2) 是否支持智能调用：被父画布引用时，这张流程的节点卡才允许「炸开」输入提示词，
--    并由大模型决定子图里每个节点是复用已有产物还是强制重生成。
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS smart_call boolean NOT NULL DEFAULT false;

-- 原子流程（只出一件产物、内部没有再嵌子流程）天然就是智能节点：图片/视频/文本卡
-- 现在的行为——炸开输入提示词直接重出——本来就是对的，这里只是把它显式记下来。
-- jsonb_typeof 的守卫别省：graph 没有 nodes 数组时 jsonb_array_elements 直接报错，
-- 而这条迁移是**每次启动都要跑一遍**的（init_pool 幂等执行 sql/*.sql）。
UPDATE workflows w SET smart_call = true
WHERE w.smart_call = false
  AND jsonb_typeof(w.graph->'nodes') = 'array'
  AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.graph->'nodes') n
              WHERE n->>'type' IN ('gen','llm'))
  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(w.graph->'nodes') n
                  WHERE n->>'type' IN ('subflow','loop'));

-- 用户设置必须扛得住「删表重建」：sql/60 每次启动都把非白名单的模板流程整行删掉，
-- 随后各自的种子文件（80/91/…）再 INSERT 回来——行上的开关届时必然回到列默认值。
-- 实测过：画布上打开「支持智能调用」，后端一重启就恢复成关闭，而且毫无痕迹。
-- 所以能力声明按 slug 存在一张独立的小表里，本文件（序号最大，跑在所有种子之后）
-- 负责把它还原到 workflows 行上。写入方只有 PATCH 接口，两处同写。
CREATE TABLE IF NOT EXISTS workflow_capabilities (
  slug        text PRIMARY KEY,
  smart_call  boolean NOT NULL DEFAULT false,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 「支持智能调用」是流程的能力声明，按 slug 全版本一致（PATCH 接口也是这个口径）。
-- 上面的启发式是逐行判的，会出现 v5 是智能节点、v4 不是——引用方固定版本，
-- 那就成了「换个版本行为就变」，正是版本化引用最忌讳的漂移。
UPDATE workflows w SET smart_call = true
WHERE w.smart_call = false
  AND EXISTS (SELECT 1 FROM workflows o WHERE o.slug = w.slug AND o.smart_call);

-- 最后一步：用户的显式设置压过启发式（开也压、关也压）。
UPDATE workflows w SET smart_call = c.smart_call
FROM workflow_capabilities c
WHERE c.slug = w.slug AND w.smart_call IS DISTINCT FROM c.smart_call;
