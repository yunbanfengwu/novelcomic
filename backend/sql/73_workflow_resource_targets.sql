-- Generic resource targets and append-only workflow artifact provenance.
ALTER TABLE workflows ADD COLUMN IF NOT EXISTS canvas_role TEXT;

CREATE TABLE IF NOT EXISTS workflow_artifacts (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    attachment_id BIGINT REFERENCES content_attachments(id) ON DELETE SET NULL,
    target_kind TEXT NOT NULL,
    target_id BIGINT NOT NULL,
    role TEXT NOT NULL DEFAULT 'primary',
    variant TEXT,
    url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workflow_artifacts_target_idx ON workflow_artifacts(target_kind,target_id,role,created_at DESC);

CREATE TABLE IF NOT EXISTS workflow_artifact_provenance (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL REFERENCES workflow_artifacts(id) ON DELETE CASCADE,
    workflow_id BIGINT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    workflow_run_id BIGINT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    workflow_node_run_id BIGINT NOT NULL REFERENCES workflow_node_runs(id) ON DELETE CASCADE,
    node_key TEXT NOT NULL,
    iteration INT NOT NULL DEFAULT 0,
    operation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workflow_artifact_provenance_node_idx ON workflow_artifact_provenance(workflow_run_id,node_key,iteration);

-- The visible contract is a typed target and an operation. config.step remains the runtime adapter.
UPDATE workflows
SET input_schema = input_schema || '{"target_ref":{"type":"resource","required":true,"desc":"关联要素或内容","seq":1,"resource_kinds":["element"]},"variant_id":{"type":"string","required":false,"desc":"图片变体","seq":2},"scene_name":{"type":"string","required":false,"ui":{"hide":true}},"element_id":{"type":"int","required":false,"ui":{"hide":true}}}'::jsonb,
    graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN n->>'type'='gen' THEN jsonb_set(n, '{config}',
        (n->'config') || jsonb_build_object('operation', COALESCE(n->'config'->>'operation', n->'config'->>'step'), 'artifact_role', COALESCE(n->'config'->>'artifact_role','scene.sheet'), 'payload', COALESCE(n->'config'->'payload','{}'::jsonb) || '{"variant_id":"{{input.variant_id}}"}'::jsonb, 'assemble', jsonb_set(COALESCE(n->'config'->'assemble','{}'::jsonb),'{args,variant_id}','"{{input.variant_id}}"'::jsonb,true)))
        ELSE n END) FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='scene-sheet-canvas' AND origin_slug IS NULL;

UPDATE workflows
SET input_schema = input_schema || '{"target_ref":{"type":"resource","required":true,"desc":"关联要素或内容","seq":1,"resource_kinds":["content_node"]},"chapter_id":{"type":"int","required":false,"ui":{"hide":true}},"shot_id":{"type":"int","required":false,"ui":{"hide":true}}}'::jsonb,
    graph = jsonb_set(graph, '{nodes}', (
      SELECT jsonb_agg(CASE WHEN n->>'type'='gen' THEN jsonb_set(n, '{config}',
        (n->'config') || jsonb_build_object('operation', COALESCE(n->'config'->>'operation', n->'config'->>'step'), 'artifact_role', COALESCE(n->'config'->>'artifact_role','shot.keyframe')))
        ELSE n END) FROM jsonb_array_elements(graph->'nodes') n))
WHERE slug='shot-keyframe-canvas' AND origin_slug IS NULL;
