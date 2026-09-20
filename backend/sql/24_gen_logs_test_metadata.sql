-- 测试台复用 gen_logs：普通生成日志不受影响，测试记录以 source='test:*' 区分。
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS test_run_id TEXT;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS test_item TEXT;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS employee_codes JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS skill_slugs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS knowledge_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS sop_code TEXT;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS planner_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE gen_logs ADD COLUMN IF NOT EXISTS duration_ms INTEGER;

CREATE INDEX IF NOT EXISTS idx_gen_logs_test_run
ON gen_logs(test_run_id, created_at DESC)
WHERE test_run_id IS NOT NULL;
