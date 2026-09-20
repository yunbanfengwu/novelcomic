-- 人物特征库（2026-07-16）：kind=prompt_block, category=persona 的系统文件夹。
-- 按年龄段沉淀「声音特征 + 言语风格」，供捏音色（选角对齐参数）与情绪小样/台词写作（语域断句）检索拼接。
-- 注意：声音特征文字不能直接喂 TTS（硅基 CosyVoice2 不吃 instruct 会念出来），只走 LLM 提示词与 speed 参数两条通道。

INSERT INTO kb_folders (name, title, kind, category, system, seq) VALUES
    ('persona_traits', '人物特征', 'prompt_block', 'persona', TRUE, 45)
ON CONFLICT (name) DO NOTHING;
