-- Expose the exact image prompt/reference set from the scene-sheet child flow.
-- Multi-element-smart-generation renders each child result as a transient card;
-- without these fields the card has an image URL but an empty generation bar.
UPDATE workflows AS w
SET output_schema = COALESCE(w.output_schema, '{}'::jsonb)
        || '{"prompt":{"type":"string"},"reference_images":{"type":"array"}}'::jsonb,
    graph = jsonb_set(
        w.graph,
        '{nodes}',
        (
            SELECT jsonb_agg(
                CASE WHEN n->>'id' = 'end' THEN
                    jsonb_set(
                        n,
                        '{config,outputs}',
                        COALESCE(n#>'{config,outputs}', '{}'::jsonb)
                            || '{"prompt":"{{gen.prompt}}","reference_images":"{{gen.reference_images}}"}'::jsonb,
                        true)
                ELSE n END
                ORDER BY ord)
            FROM jsonb_array_elements(w.graph->'nodes') WITH ORDINALITY AS item(n, ord)
        ),
        false),
    updated_at = now()
WHERE w.slug = 'scene-sheet-canvas'
  AND w.version = 8
  AND NOT EXISTS (
      SELECT 1
      FROM jsonb_array_elements(w.graph->'nodes') AS item(n)
      WHERE n->>'id' = 'end'
        AND n#>>'{config,outputs,prompt}' = '{{gen.prompt}}'
        AND n#>>'{config,outputs,reference_images}' = '{{gen.reference_images}}'
  );
