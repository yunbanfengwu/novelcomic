-- Shot-video canvas reference-material source (idempotent, 2026-09-20).
-- The video canvas's prepare_context had no material source upstream (it was
-- wired to `start` only), so reference materials never reached the canvas:
-- "已读取 0 个上游参考素材" even when the shot already had element sheets,
-- user references, storyboard images and a keyframe loaded in the business
-- tables.  Insert a read-only `canvas.collect_refs` node between start and
-- prepare_context so refs flow through the standard __in__ aggregation into
-- both the canvas echo (preview/restore) and the generation prompt.
--
-- Applies to the template AND every existing shot-video-canvas instance
-- (forks keep a graph snapshot at fork time; without this backfill old
-- instances would keep showing zero references).

CREATE OR REPLACE FUNCTION append_canvas_shot_refs_node(p_slug text, p_is_template boolean)
RETURNS int
LANGUAGE plpgsql AS $$
DECLARE
    target_id bigint;
    current_graph jsonb;
    new_nodes jsonb;
    new_edges jsonb;
    refs_node jsonb;
BEGIN
    SELECT id, graph INTO target_id, current_graph
      FROM workflows
     WHERE slug = p_slug
       AND ((p_is_template AND origin_slug IS NULL) OR (NOT p_is_template AND origin_slug IS NOT NULL))
     ORDER BY version DESC
     LIMIT 1;
    IF current_graph IS NULL THEN
        RETURN 0;
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(current_graph->'nodes','[]'::jsonb)) n
         WHERE n->>'id' = 'shot_refs'
    ) THEN
        RETURN 0;
    END IF;
    -- Only patch graphs that actually have the standard preparation node.
    IF NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(current_graph->'nodes','[]'::jsonb)) n
         WHERE n->>'id' = 'prepare_context'
    ) THEN
        RETURN 0;
    END IF;

    refs_node := jsonb_build_object(
        'id', 'shot_refs',
        'type', 'action',
        'position', jsonb_build_object('x', 130, 'y', 60),
        'config', jsonb_build_object(
            'name', 'canvas.collect_refs',
            'args', jsonb_build_object(
                'project_id', '{{input.project_id}}',
                'shot_id', '{{input.shot_id}}'
            ),
            'ui', jsonb_build_object(
                'tap', 'text',
                'title', 'Collect shot references',
                'show', 'summary',
                'w', 380,
                'h', 240
            )
        )
    );
    new_nodes := COALESCE(current_graph->'nodes','[]'::jsonb) || jsonb_build_array(refs_node);
    new_edges := COALESCE(current_graph->'edges','[]'::jsonb) || jsonb_build_array(
        jsonb_build_object('from','start','to','shot_refs'),
        jsonb_build_object('from','shot_refs','to','prepare_context')
    );

    UPDATE workflows
       SET graph = jsonb_set(
                    jsonb_set(current_graph, '{nodes}', new_nodes),
                    '{edges}', new_edges
                  ),
           updated_at = now()
     WHERE id = target_id;
    RETURN 1;
END;
$$;

SELECT append_canvas_shot_refs_node('shot-video-canvas', true) AS template_patched;

-- Legacy instances forked before the 106 preparation stage lack
-- prepare_context entirely (their graph is a snapshot of the old template);
-- refresh them from the current template so they pick up both stages at once.
UPDATE workflows inst
   SET graph = tpl.graph, updated_at = now()
  FROM workflows tpl
 WHERE tpl.slug = 'shot-video-canvas' AND tpl.origin_slug IS NULL
   AND inst.slug LIKE 'shot-video-canvas@%'
   AND inst.origin_slug IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM jsonb_array_elements(inst.graph->'nodes') n
        WHERE n->>'id' = 'prepare_context')
   AND EXISTS (
       SELECT 1 FROM jsonb_array_elements(tpl.graph->'nodes') n
        WHERE n->>'id' = 'shot_refs');

DO $$
DECLARE
    r record;
    total int := 0;
BEGIN
    FOR r IN SELECT slug FROM workflows
             WHERE slug LIKE 'shot-video-canvas@%' AND origin_slug IS NOT NULL
    LOOP
        total := total + append_canvas_shot_refs_node(r.slug, false);
    END LOOP;
    RAISE NOTICE 'shot-video-canvas instances patched: %', total;
END $$;

DROP FUNCTION append_canvas_shot_refs_node(text, boolean);

-- "缺才跑" at the parent level: if the shot already has a keyframe, the
-- ensure_keyframe subflow must not re-enter the child canvas (its continuity
-- guard would fail on legacy shots that predate the continuity pipeline).
-- gen_video's before() re-reads meta.keyframe_url itself, so a skipped
-- subflow never starves the I2V anchor.
DO $$
DECLARE
    r record;
    new_nodes jsonb;
    skip_if jsonb;
BEGIN
    skip_if := jsonb_build_object(
        'sql', 'SELECT meta->>''keyframe_url'' FROM content_nodes WHERE id=$1',
        'args', jsonb_build_array('{{input.shot_id}}'),
        'reason', '已有分镜关键帧，直接复用（缺才跑）');
    FOR r IN SELECT id, graph FROM workflows
             WHERE (slug = 'shot-video-canvas' AND origin_slug IS NULL)
                OR (slug LIKE 'shot-video-canvas@%' AND origin_slug IS NOT NULL)
    LOOP
        IF EXISTS (
            SELECT 1 FROM jsonb_array_elements(r.graph->'nodes') n
             WHERE n->>'id' = 'ensure_keyframe'
               AND (n->'config'->>'skip_if') IS NULL
        ) THEN
            SELECT jsonb_agg(
                       CASE WHEN n->>'id' = 'ensure_keyframe'
                            THEN jsonb_set(n, '{config,skip_if}', skip_if) ELSE n END
                       ORDER BY ord)
              INTO new_nodes
              FROM jsonb_array_elements(r.graph->'nodes') WITH ORDINALITY AS x(n, ord);
            UPDATE workflows
               SET graph = jsonb_set(r.graph, '{nodes}', new_nodes), updated_at = now()
             WHERE id = r.id;
        END IF;
    END LOOP;
END $$;
