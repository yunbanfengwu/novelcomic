-- Asset type is a code-defined backend contract. This table only indexes instances and keeps legacy fields intact.
ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS asset_type TEXT;
ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS subject_kind TEXT;
ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS subject_id BIGINT;
ALTER TABLE workflow_artifacts ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1;

UPDATE workflow_artifacts
SET asset_type = CASE role
  WHEN 'scene.sheet' THEN 'pro.scene.sheet'
  WHEN 'shot.keyframe' THEN 'pro.shot.keyframe'
  WHEN 'character.sheet' THEN 'pro.character.sheet'
  WHEN 'prop.sheet' THEN 'pro.prop.sheet'
  ELSE asset_type END,
  subject_kind = COALESCE(subject_kind, target_kind),
  subject_id = COALESCE(subject_id, target_id)
WHERE asset_type IS NULL OR subject_kind IS NULL OR subject_id IS NULL;

CREATE INDEX IF NOT EXISTS workflow_artifacts_asset_type_idx
  ON workflow_artifacts(project_id, asset_type, subject_kind, subject_id, variant, version DESC, id DESC);
