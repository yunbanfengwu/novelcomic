// 引导式新建项目的步骤定义（像 macOS 开机引导：分步、可跳过、后续补充）。
// 纯常量表，零 JSX——图标名交给 <Icon name>，各步 UI 在 features/projects/guide/steps/。

export type GuideStepKey = 'basic' | 'materials' | 'writing' | 'art' | 'preview'

export interface GuideStepMeta {
  key: GuideStepKey
  icon: string     // components/Icon.tsx 图标名
  label: string    // 左侧步骤名
  hint: string     // 右侧标题下的一句话说明
}

export const GUIDE_STEPS: GuideStepMeta[] = [
  { key: 'art', icon: 'palette', label: '画面设定', hint: '先定画幅比例与作品类型（视频类型标签），再选画风；绘画员工据此出图，风格可留空由 AI 拟定。' },
  { key: 'basic', icon: 'clipboard', label: '基本信息', hint: '草稿必填；书名、梗概与主线可留空，或点草稿框右下角星标一键智能生成。' },
  { key: 'materials', icon: 'clip', label: '相关材料', hint: '粘贴构思或上传原始小说（文件即传即得 URL，其余随创建一并保存）。' },
  { key: 'writing', icon: 'pen', label: '内容设定', hint: '本作的写作风格与语言指令，写作员工据此落笔；可留空由 AI 拟定。' },
  { key: 'preview', icon: 'search', label: '设定预览', hint: '过一遍各步设定——确认无误后在这里创建项目。' },
]
