// 画布动作冒烟：tapflow scope 下让模型改提示词 + 触发单节点运行，验证 ACTION 流
const BASE = 'http://127.0.0.1:8765'
const H = { 'Content-Type': 'application/json', 'X-User-Id': 'sys_dev' }
const SCOPE = { scope_kind: 'tapflow', scope_key: 'project-trailer-canvas@1' }

const CTX = `画布《先导预告片·画布》v1
节点清单（行首为节点 key，AI 引用节点时用它）：
- start（start）开始
- gen（gen）生成预告片【当前选中】
- end（next）保存预告片`

async function main() {
  const conv = await (await fetch(`${BASE}/api/chat/conversations`, {
    method: 'POST', headers: H, body: JSON.stringify({ ...SCOPE, fresh: false }),
  })).json()
  await fetch(`${BASE}/api/chat/conversations/${conv.id}/messages`, {
    method: 'POST', headers: H,
    body: JSON.stringify({ role: 'user', content: '把生成预告片节点的提示词改成「15秒竖屏硬切蒙太奇：雨夜霓虹街头，主角奔跑回望，结尾定格抬头」。只改提示词，先不要运行。' }),
  })
  const r = await fetch(`${BASE}/api/chat/conversations/${conv.id}/reply/stream`, {
    method: 'POST', headers: H, body: JSON.stringify({ context: CTX }),
  })
  const dec = new TextDecoder()
  let buf = ''
  const reader = r.body.getReader()
  let text = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2)
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data:')) continue
        const ev = JSON.parse(line.slice(5))
        if (ev.event === 'step') console.log('[step]', ev.title, ev.detail ?? '')
        else if (ev.event === 'action') console.log('[ACTION]', JSON.stringify(ev.action))
        else if (ev.event === 'delta') text += ev.text
        else if (ev.event === 'suggestions') console.log('[suggestions]', ev.items)
        else if (ev.event === 'done') console.log('[done] saved msg id', ev.message.id)
        else if (ev.event === 'error') console.log('[ERROR]', ev.title)
      }
    }
  }
  console.log('── 正文：', text.trim().slice(0, 200))
}
main().catch(e => { console.error('FAIL', e); process.exit(1) })
