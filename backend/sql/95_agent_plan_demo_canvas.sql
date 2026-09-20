-- 「按上下文规划」节点的验证画布（2026-08-07 新增）。
--
-- 存在的目的只有一个：让 agent.plan 能在**真实运行期 ctx**里被观察到——开始节点即项目/章节
-- 签名，规划节点自己分页读 ctx、查能力目录、多轮收敛。不新写任何画布 UI：走的就是
-- 现有 tapflow 画布（系统管理 → tapflow）。
--
-- 刻意只挂只读工具（ctx.* 由引擎自动挂，capability.* 只校验不执行），所以这张图
-- 反复跑不花钱、不落库，可以拿来观察模型的取数路径。
-- tags 必须含 'canvas'：tapflow 列表页（lib/tapflowLoad.latestCanvasFlows）就按这个标签
-- 筛，漏了它这张图存在但列表上看不见。'text' 让它归到文本类而不是出图类。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema,
                      graph, seq, tags)
VALUES (
  'agent-plan-demo',
  '按上下文规划·验证',
  '验证 agent.plan：模型自己分页读 ctx（outline→search→get）、查能力目录、判断缺哪些前置能力，'
  '多轮收敛后给出九宫格分镜要素的组装结果。全程只读，反复跑不花钱。',
  1, 'published',
  '{"project_id":{"type":"int","required":true,"seq":0,"label":"项目"},
    "chapter_id":{"type":"int","required":false,"seq":1,"label":"章节","desc":"留空则只按项目规划"}}'::jsonb,
  '{"plan":{"type":"string"},"read_path":{"type":"array"},"step_count":{"type":"int"}}'::jsonb,
  '{"nodes":[
      {"id":"start","type":"start","config":{"ui":{"title":"项目上下文","x":80,"y":160}}},
      {"id":"plan","type":"action","config":{
         "name":"agent.plan",
         "ui":{"title":"按上下文规划","tap":"tool","x":380,"y":160},
         "args":{
           "goal":"目标：为本章生成九宫格分镜要素提示词。\n先用 ctx.outline 看清上游到底给了什么，不要假设；需要正文再按 offset 分页读，别一次性全取。\n然后用 capability.catalog 查有哪些能力可用，判断要产出九宫格还缺哪些前置产物（分镜脚本、画面定格、要素参考等），对每个候选用 capability.plan_invoke 校验入参是否齐备。\n最后输出三段：一、上下文里已有什么；二、还缺什么，各该调哪个能力（写 id 与入参）；三、如果前置齐备，直接给出九宫格分镜要素提示词。",
           "tool_names":["capability.catalog","capability.plan_invoke","db.schema","db.query"],
           "max_steps":20,
           "project_id":"{{start.project_id}}"
         }}},
      {"id":"end","type":"end","config":{
         "ui":{"title":"规划结果","x":700,"y":160},
         "outputs":{"plan":"{{plan.output}}","read_path":"{{plan.read_path}}",
                    "step_count":"{{plan.step_count}}"}}}
    ],
    "edges":[{"from":"start","to":"plan"},{"from":"plan","to":"end"}]}'::jsonb,
  990, ARRAY['canvas', 'text', 'agent-plan']
)
ON CONFLICT (slug, version) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  status = EXCLUDED.status,
  input_schema = EXCLUDED.input_schema,
  output_schema = EXCLUDED.output_schema,
  graph = EXCLUDED.graph,
  seq = EXCLUDED.seq,
  tags = EXCLUDED.tags,
  updated_at = now();
