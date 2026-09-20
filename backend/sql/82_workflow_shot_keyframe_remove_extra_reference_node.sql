-- “额外参考资产”不是关键帧工作流的内置业务步骤：需要参考图时，用户在画布
-- 自行添加普通图片节点并连入生成节点。迁移已有 v1 画布，且可重复执行。
UPDATE workflows
SET
  description = '分镜事实与脚本 + 智能动态要素资产 → 关键帧生成。动态要素从分镜持久化关联读取，并由资产类型工作流统一路由。',
  graph = jsonb_set(
    jsonb_set(
      graph,
      '{nodes}',
      COALESCE((
        SELECT jsonb_agg(node.value ORDER BY node.ordinality)
        FROM jsonb_array_elements(graph->'nodes') WITH ORDINALITY AS node(value, ordinality)
        WHERE node.value->>'id' <> 'extra_refs'
      ), '[]'::jsonb)
    ),
    '{edges}',
    COALESCE((
      SELECT jsonb_agg(edge.value ORDER BY edge.ordinality)
      FROM jsonb_array_elements(graph->'edges') WITH ORDINALITY AS edge(value, ordinality)
      WHERE edge.value->>'from' <> 'extra_refs'
        AND edge.value->>'to' <> 'extra_refs'
    ), '[]'::jsonb)
  ),
  updated_at = now()
WHERE slug = 'shot-keyframe-canvas'
  AND version = 1
  AND graph IS NOT NULL;
