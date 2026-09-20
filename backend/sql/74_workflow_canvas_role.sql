-- A target may have several product slots. Scope an instance by role/variant, not only its parent element.
DROP INDEX IF EXISTS workflows_instance_subject_idx;
CREATE UNIQUE INDEX IF NOT EXISTS workflows_instance_subject_role_idx
    ON workflows (origin_slug, subject_kind, subject_id, COALESCE(canvas_role,''), version)
    WHERE subject_id IS NOT NULL;
