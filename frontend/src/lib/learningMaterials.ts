export interface LearningMaterial {
  key: string
  title: string
  desc: string
  /** public/ 下的静态文件路径，用 iframe 直接嵌入 */
  src: string
}

// 学习资料清单：静态文件放在 frontend/public/learning/ 下，新增资料时在此登记即可
export const LEARNING_MATERIALS: LearningMaterial[] = [
  {
    key: 'seedance2-prompts',
    title: 'Seedance2.0 提示词与运镜方法',
    desc: '火山引擎推荐：20 个提示词万能方法 + 40 个运镜方法整理',
    src: '/learning/seedance2-prompts.html',
  },
]
