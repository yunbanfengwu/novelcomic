-- 核心要素图片生成画布（2026-08-02）：素材库「角色/场景/道具等所有图片」的 tapflow 生成入口。
-- 素材库设定图画廊的生成/重生成统一走这张生产态画布（ElementPreview.openElementImageTapflow）：
-- 打开即带 project_id + target_ref(element:{id}) [+ variant_id]，画布跑完素材库立即可见。
--
-- 为什么**不**按资产类型各建一张：引擎的资产输入合同是「一张画布恰好声明一个 asset_type」
-- （workflow._apply_asset_type_contract：声明的资产类型数≠1 时直接丢弃入参 asset_type），
-- 素材库要的是一张画布通吃角色/场景/道具，所以这张画布不带资产类型合同。
-- 目标绑定两条路径，info 节点(element.get)统一解析出 element_id 供下游引用：
--   ① 素材库画布路径：运行入参只带 target_ref(element:{id})，start_run 的 normalize_inputs
--     会把它展开成 element_id；element.get 也直接收 target_ref（空串当未填）。
--   ② 工作流列表/智能参数卡路径：canonical_inputs 把「素材」选择器解析成 element_id 直填。
--
-- 生成节点用 **gen**（不是 task）：gen 走引擎的装配/参考图/缺才跑机制——
-- assemble=element.layers（角色/场景/道具通用的分层装配器：user=要素叙事+画风锚、
-- anchor=版式/画风/质量、hair=角色发型发饰小卡、refs=要素现有设定图）；参考图两个入口，
-- 都归进同一份 reference_images（≤4 张，_apply_refs）：①节点卡上「+ 参考图」上传的静态图
-- （存 payload.reference_images，引擎排最优先）②上游连线的节点产物（按入边序收）。
-- 连文本节点则并入提示词；生成条可手改最终提示词（手编冻结语义）。
-- 执行体仍指名产线的 gen_element_sheet：落 content_attachments + 回写要素
-- variants[].sheet_url + 外貌指纹（素材库画廊立即可见），装配本体与 API 端点同源。
--
-- 注意（2026-08-02）：本文件曾以 element_sheet.prepare + task 节点的形态先落过一版
-- （无参考图节点/无补充要求/智能卡填不进素材），这里以 gen 版整体替换——
-- 用 DO UPDATE 而非 DO NOTHING 正是为修正已误播的 v1 模板行。
INSERT INTO workflows(slug, name, description, version, status, input_schema, output_schema, graph, seq, tags)
VALUES (
  'core-element-image-generation', '核心要素图片生成',
  '项目 + 素材要素（target_ref 或 element_id）→ 素材信息 → 分层装配(element.layers) + 参考图 → gen_element_sheet 出图回写设定图。',
  1, 'published',
  '{"project_id": {"type": "int", "required": true, "desc": "项目", "seq": 0}, "target_ref": {"type": "string", "required": false, "desc": "素材要素引用（element:{id}，素材库画布路径）", "seq": 1}, "element_id": {"type": "int", "required": false, "desc": "素材要素（角色/场景/道具；与 target_ref 等价）", "seq": 2}, "variant_id": {"type": "string", "required": false, "desc": "造型变体 id，留空取主造型", "seq": 3}, "instruction": {"type": "string", "required": false, "desc": "补充要求（可空，留空则按要素档案生成）", "seq": 4}}'::jsonb,
  '{"sheet_url": {"type": "string", "desc": "生成的设定图地址"}, "element_id": {"type": "int", "desc": "核心要素 ID"}, "variant_id": {"type": "string", "desc": "造型变体 ID"}}'::jsonb,
  $g${
 "nodes": [
  {
   "id": "start",
   "type": "start",
   "position": {
    "x": 40,
    "y": 220
   },
   "config": {
    "ui": {
     "tap": "start",
     "title": "核心要素图片输入"
    }
   }
  },
  {
   "id": "info",
   "type": "action",
   "position": {
    "x": 400,
    "y": 220
   },
   "config": {
    "name": "element.get",
    "args": {
     "project_id": "{{input.project_id}}",
     "element_id": "{{input.element_id}}",
     "target_ref": "{{input.target_ref}}"
    },
    "ui": {
     "tap": "text",
     "title": "素材信息",
     "show": "summary",
     "w": 360,
     "h": 280
    }
   }
  },
  {
   "id": "gen",
   "type": "gen",
   "position": {
    "x": 820,
    "y": 180
   },
   "config": {
    "modality": "image",
    "assemble": {
     "name": "element.layers",
     "args": {
      "project_id": "{{input.project_id}}",
      "element_id": "{{info.id}}",
      "variant_id": "{{input.variant_id}}"
     }
    },
    "step": "gen_element_sheet",
    "instruction": "{{input.instruction}}",
    "payload": {
     "element_id": "{{info.id}}",
     "variant_id": "{{input.variant_id}}"
    },
    "skip_if": {
     "sql": "SELECT COALESCE((SELECT v->>'sheet_url' FROM jsonb_array_elements(COALESCE(meta->'variants','[]'::jsonb)) v WHERE v->>'id'=COALESCE($2,'default') LIMIT 1), CASE WHEN COALESCE($2,'default')='default' THEN meta->>'sheet_url' END) FROM content_elements WHERE id=$1",
     "args": [
      "{{info.id}}",
      "{{input.variant_id}}"
     ],
     "reason": "该要素这个形态已有设定图,跳过(选中节点→重新生成 可强制重出)"
    },
    "ui": {
     "tap": "gen",
     "title": "设定图生成 · {{info.name}}",
     "w": 520,
     "h": 300,
     "model": "系统出图模型"
    }
   }
  },
  {
   "id": "end",
   "type": "end",
   "position": {
    "x": 1400,
    "y": 210
   },
   "config": {
    "outputs": {
     "sheet_url": "{{gen.url}}",
     "element_id": "{{info.id}}",
     "variant_id": "{{input.variant_id}}"
    },
    "ui": {
     "tap": "next",
     "title": "next · 回写与通知",
     "next": {
      "writes": [
       "要素 · 设定图 variants[].sheet_url"
      ],
      "attach": true,
      "notify": [
       "任务中心"
      ]
     }
    }
   }
  }
 ],
 "edges": [
  {
   "from": "start",
   "to": "info"
  },
  {
   "from": "info",
   "to": "gen"
  },
  {
   "from": "gen",
   "to": "end"
  }
 ]
}$g$::jsonb,
  910, '{canvas,图片,核心要素,素材库}'::text[]
)
ON CONFLICT (slug, version) DO UPDATE SET
  name=excluded.name, description=excluded.description, status=excluded.status,
  input_schema=excluded.input_schema, output_schema=excluded.output_schema,
  graph=excluded.graph, seq=excluded.seq, tags=excluded.tags, updated_at=now();
