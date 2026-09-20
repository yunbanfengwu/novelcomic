-- ═══════════════ 附件互引：素材关联其他素材 ═══════════════
-- 附件表自引用列：一条素材可关联到本表另一条素材。
-- 当前用途：视频 → 其首帧封面图（抽帧后同样落 content_attachments 的 image 行）。
-- ON DELETE SET NULL：封面图被删只断链，不连带删视频；反之视频删除时其封面图不受此列牵连。
ALTER TABLE content_attachments
  ADD COLUMN IF NOT EXISTS cover_attachment_id BIGINT
  REFERENCES content_attachments(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS content_attachments_cover_idx
  ON content_attachments (cover_attachment_id);

COMMENT ON COLUMN content_attachments.cover_attachment_id IS
  '关联本表其他素材：视频行→其首帧封面图（image 行）；ON DELETE SET NULL 断链不连带删';
