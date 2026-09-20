-- SOP 的人类可编辑源文本；spec 是由人工可视化编辑或大模型编译出的确定性执行产物。
ALTER TABLE visual_sops ADD COLUMN IF NOT EXISTS source_text TEXT NOT NULL DEFAULT '';
ALTER TABLE visual_sops ADD COLUMN IF NOT EXISTS compiled_meta JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE visual_sops
SET source_text = CASE
  WHEN spec->>'sop_type'='composite' THEN
    title || E'\n\n目标：按依赖关系调用多个独立 SOP 完成组合生产流程。\n'
    || E'before：检查输入事实、依赖和上游状态。\n'
    || E'run：执行已启用的子 SOP；无依赖的节点允许并行。\n'
    || E'next：质检、保存版本并触发下游。'
  ELSE
    title || E'\n\n目标：生成对应生产产物。\n'
    || E'before：检查事实、依赖、参考资料，调用所需 Skill 与知识。\n'
    || E'run：完成规划、提示词生成、提示词质检和模型执行。\n'
    || E'next：完成结果质检、版本保存和下游触发。'
  END
WHERE source_text='';

-- 修复曾由 Windows PowerShell 错误编码写入的封面 SOP 标题；只更新目标 code，不影响版本数据。
UPDATE visual_sops SET title='封面海报 SOP', updated_at=now()
WHERE code='cover_poster_sop' AND title <> '封面海报 SOP';
