-- 把多要素画布的隐藏 action 升级为真正可编排的工具节点。
-- 只改 config.ui，工具名、args、循环 source/body 和业务执行语义均保持不变。
-- WHERE 精确判断旧状态，后端每次启动重复执行时不会反复改 updated_at。
UPDATE workflows AS workflow
SET graph = jsonb_set(
        workflow.graph,
        '{nodes}',
        (
            SELECT jsonb_agg(
                CASE WHEN node->>'id' = 'resolve_descriptors'
                    THEN jsonb_set(
                        node,
                        '{config,ui}',
                        COALESCE(node#>'{config,ui}', '{}'::jsonb)
                            - 'hide'
                            || '{"tap":"tool","title":"按类型查询关联要素","w":460,"h":280}'::jsonb,
                        true
                    )
                    ELSE node
                END
                ORDER BY ord
            )
            FROM jsonb_array_elements(workflow.graph->'nodes') WITH ORDINALITY AS item(node, ord)
        ),
        false
    ),
    updated_at = now()
WHERE workflow.slug = 'multi-element-smart-generation'
  AND workflow.version = 1
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(workflow.graph->'nodes') AS item(node)
      WHERE node->>'id' = 'resolve_descriptors'
        AND (
            COALESCE(node#>>'{config,ui,tap}', '') <> 'tool'
            OR COALESCE((node#>>'{config,ui,hide}')::boolean, false)
        )
  );
