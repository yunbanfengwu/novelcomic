-- A keyframe canvas is shot-scoped.  Do not present chapters/volumes as valid
-- target references: they cannot supply continuity, script, or dynamic elements.
UPDATE workflows
SET input_schema = jsonb_set(
      input_schema,
      '{target_ref,resource_kinds}',
      '["content_node:shot"]'::jsonb
    ),
    updated_at = now()
WHERE slug = 'shot-keyframe-canvas'
  AND version = 1;
