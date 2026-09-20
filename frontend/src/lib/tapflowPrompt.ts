// 提示词的「文本 + 行内标签」互转（纯逻辑，零 JSX）。
// 存的仍是一个字符串，标签就是 {{...}} 占位符——这样运行时的解析口径与后端一致，
// 不为了富文本编辑另造一套存储格式。

export interface TapPromptPart {
  /** 普通文本段 */
  text?: string
  /** 行内标签的占位符，如 {{场景介绍.brief}} */
  token?: string
}

const TOKEN = /(\{\{[^{}]+\}\})/g

/** 字符串 → 段落序列（文本段与标签段交替）。 */
export function parsePrompt(value: string): TapPromptPart[] {
  const out: TapPromptPart[] = []
  for (const chunk of (value || '').split(TOKEN)) {
    if (!chunk) continue
    if (chunk.startsWith('{{') && chunk.endsWith('}}')) out.push({ token: chunk })
    else out.push({ text: chunk })
  }
  return out
}

/** 占位符 → 标签上显示的名字：优先用引用清单里的展示名，认不出就去掉花括号。 */
export function tokenLabel(token: string, names: Record<string, string>): string {
  return names[token] ?? token.replace(/^\{\{|\}\}$/g, '')
}

/** 编辑器 DOM → 字符串。标签节点还原成占位符，换行还原成 \n。
 * contenteditable 里换行可能是 <br>，也可能是被包成 <div>/<p>，两种都要认。 */
export function serializePrompt(root: HTMLElement): string {
  let out = ''
  const walk = (node: Node, topLevel: boolean) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        out += child.textContent ?? ''
        continue
      }
      if (!(child instanceof HTMLElement)) continue
      const token = child.dataset.token
      if (token) {
        out += token
        continue
      }
      if (child.tagName === 'BR') {
        out += '\n'
        continue
      }
      // 块级元素各自成行（第一个块不补前导换行，否则每次编辑都会多出一行）
      if (topLevel && out && !out.endsWith('\n')) out += '\n'
      walk(child, false)
    }
  }
  walk(root, true)
  return out
}
