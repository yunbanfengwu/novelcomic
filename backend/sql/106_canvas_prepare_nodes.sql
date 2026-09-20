-- Universal Tapflow preparation stage (idempotent, 2026-09-19).
-- Every production canvas gets a visible, executable preparation node before
-- its first generation/action node.  It reads upstream node outputs and keeps
-- system context out of the user-facing chat transcript.

CREATE OR REPLACE FUNCTION append_canvas_prepare_node(
    p_slug text, p_next text, p_purpose text
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    target_id bigint;
    current_graph jsonb;
    new_nodes jsonb;
    new_edges jsonb;
    prep_node jsonb;
BEGIN
    SELECT id, graph INTO target_id, current_graph
      FROM workflows
     WHERE slug = p_slug AND origin_slug IS NULL
     ORDER BY version DESC
     LIMIT 1;
    IF current_graph IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(current_graph->'nodes','[]'::jsonb)) n
         WHERE n->>'id' = 'prepare_context'
    ) THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(current_graph->'edges','[]'::jsonb)) e
         WHERE e->>'from' = 'start' AND e->>'to' = p_next
    ) THEN
        RETURN;
    END IF;

    prep_node := jsonb_build_object(
        'id', 'prepare_context',
        'type', 'action',
        'position', jsonb_build_object('x', 220, 'y', 180),
        'config', jsonb_build_object(
            'name', 'canvas.prepare_context',
            'args', jsonb_build_object(
                'project_id', '{{input.project_id}}',
                'purpose', p_purpose,
                'prompt', '{{input.prompt}}'
            ),
            'ui', jsonb_build_object(
                'tap', 'text',
                'title', 'Prepare upstream context',
                'show', 'summary',
                'w', 420,
                'h', 300
            )
        )
    );
    new_nodes := COALESCE(current_graph->'nodes','[]'::jsonb) || jsonb_build_array(prep_node);
    SELECT COALESCE(jsonb_agg(e ORDER BY ord), '[]'::jsonb)
      INTO new_edges
      FROM jsonb_array_elements(COALESCE(current_graph->'edges','[]'::jsonb))
           WITH ORDINALITY AS x(e, ord)
     WHERE NOT (e->>'from' = 'start' AND e->>'to' = p_next);
    new_edges := new_edges || jsonb_build_array(
        jsonb_build_object('from','start','to','prepare_context'),
        jsonb_build_object('from','prepare_context','to',p_next)
    );

    UPDATE workflows
       SET graph = jsonb_set(
                    jsonb_set(current_graph, '{nodes}', new_nodes),
                    '{edges}', new_edges
                  ),
           updated_at = now()
     WHERE id = target_id;
END;
$$;

SELECT append_canvas_prepare_node('asset-image-canvas', 'gen', 'image');
SELECT append_canvas_prepare_node('asset-video-canvas', 'gen', 'video');
SELECT append_canvas_prepare_node('project-trailer-canvas', 'gen', 'trailer');
SELECT append_canvas_prepare_node('scene-group-canvas', 'gen_empty', 'scene_group');
SELECT append_canvas_prepare_node('shot-keyframe-canvas', 'context', 'shot_keyframe');
SELECT append_canvas_prepare_node('shot-video-canvas', 'ensure_keyframe', 'shot_video');
SELECT append_canvas_prepare_node('shot-lastframe-canvas', 'context', 'last_frame');
SELECT append_canvas_prepare_node('storyboard-grid-canvas', 'gen', 'storyboard');
SELECT append_canvas_prepare_node('batch-keyframe-canvas', 'plan', 'keyframe_batch');
SELECT append_canvas_prepare_node('scene-sheet-canvas', 'ensure', 'scene');
SELECT append_canvas_prepare_node('core-element-image-generation', 'info', 'core_element');

-- The nine-grid canvas has two start branches (asset discovery and final
-- generation).  Route both branches through the same preparation node.
DO $$
DECLARE
    current_graph jsonb;
    nodes jsonb;
    edges jsonb;
BEGIN
    SELECT graph INTO current_graph
      FROM workflows
     WHERE slug = 'nine-grid-keyframe-reference' AND version = 1
       AND origin_slug IS NULL
     LIMIT 1;
    IF current_graph IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(current_graph->'nodes','[]'::jsonb)) n
         WHERE n->>'id' = 'prepare_context'
    ) THEN
        nodes := COALESCE(current_graph->'nodes','[]'::jsonb) || jsonb_build_array(
            jsonb_build_object(
                'id','prepare_context','type','action',
                'position',jsonb_build_object('x',220,'y',200),
                'config',jsonb_build_object(
                    'name','canvas.prepare_context',
                    'args',jsonb_build_object(
                        'project_id','{{input.project_id}}',
                        'purpose','storyboard_nine_grid',
                        'prompt','{{input.grid_prompt}}'
                    ),
                    'ui',jsonb_build_object(
                        'tap','text','title','Prepare storyboard references',
                        'show','summary','w',420,'h',300
                    )
                )
            )
        );
        SELECT COALESCE(jsonb_agg(e ORDER BY ord), '[]'::jsonb)
          INTO edges
          FROM jsonb_array_elements(COALESCE(current_graph->'edges','[]'::jsonb))
               WITH ORDINALITY AS x(e, ord)
         WHERE e->>'from' <> 'start';
        edges := edges || jsonb_build_array(
            jsonb_build_object('from','start','to','prepare_context'),
            jsonb_build_object('from','prepare_context','to','elements'),
            jsonb_build_object('from','prepare_context','to','generate')
        );
        UPDATE workflows
           SET graph = jsonb_set(
                        jsonb_set(current_graph, '{nodes}', nodes),
                        '{edges}', edges
                      ),
               updated_at = now()
         WHERE slug = 'nine-grid-keyframe-reference' AND version = 1
           AND origin_slug IS NULL;
    END IF;
END;
$$;

DROP FUNCTION append_canvas_prepare_node(text, text, text);

-- A dedicated poster canvas uses the same three-stage contract:
-- read project anchors -> generate/persist poster -> end/output.
INSERT INTO workflows(
    slug, name, description, version, status, input_schema, output_schema,
    graph, seq, tags
)
VALUES (
    'project-poster-canvas',
    'Project poster canvas',
    'Read project visual anchors, generate and persist the project cover poster.',
    1, 'published',
    '{"project_id":{"type":"int","required":true,"desc":"project","seq":0},
      "prompt":{"type":"string","desc":"optional poster request","seq":1}}'::jsonb,
    '{"poster_url":{"type":"string"},"prompt":{"type":"string"}}'::jsonb,
    $g${
      "nodes":[
        {"id":"start","type":"start","position":{"x":40,"y":240},
         "config":{"ui":{"tap":"start","title":"Start"}}},
        {"id":"prepare_context","type":"action","position":{"x":240,"y":180},
         "config":{"name":"project_visual.prepare",
                   "args":{"project_id":"{{input.project_id}}","role":"project_cover_poster","prompt":"{{input.prompt}}"},
                   "ui":{"tap":"text","title":"Prepare project visual references","show":"summary","w":420,"h":300}}},
        {"id":"gen","type":"action","position":{"x":800,"y":180},
         "config":{"name":"project_visual.generate",
                   "args":{"project_id":"{{input.project_id}}","role":"project_cover_poster",
                           "prompt":"{{prepare_context.prompt}}","reference_urls":"{{prepare_context.reference_images}}"},
                   "ui":{"tap":"gen","title":"Generate project poster","w":460,"h":273,"model":"current image model"}}},
        {"id":"end","type":"end","position":{"x":1360,"y":230},
         "config":{"outputs":{"poster_url":"{{gen.url}}","prompt":"{{gen.prompt}}"},
                   "ui":{"tap":"next","title":"Save project poster",
                         "next":{"attach":true,"notify":["task center"],"writes":["project_visual_assets","content_attachments"]}}}}
      ],
      "edges":[{"from":"start","to":"prepare_context"},
               {"from":"prepare_context","to":"gen"},
               {"from":"gen","to":"end"}]
    }$g$::jsonb,
    966, '{canvas,poster,project_visual}'::text[]
)
ON CONFLICT(slug, version) DO NOTHING;
