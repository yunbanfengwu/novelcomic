-- 运行期可编辑的全局系统配置：key-value，value 用 jsonb 存整块结构。
-- 目前只有一条 key='home_bg'：首页背景多组（轮播）配置，前端当前只取第一组。
CREATE TABLE IF NOT EXISTS app_config (
  key        text PRIMARY KEY,
  value      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
