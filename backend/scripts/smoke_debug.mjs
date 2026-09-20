// 流式规划回复接口冒烟：建会话 → 发用户消息 → SSE 读流，打印事件序列
const BASE = 'http://127.0.0.1:8766'
const H = { 'Content-Type': 'application/json', 'X-User-Id': 'sys_dev' }

async function main() {
  const conv = await (await fetch(`${BASE}/api/chat/conversations`, {
    method: 'POST', headers: H,
    body: JSON.stringify({ scope_kind: 'global', scope_key: 'global', fresh: true }),
  })).json()
  const cid = conv.id
  await fetch(`${BASE}/api/chat/conversations/${cid}/messages`, {
    method: 'POST', headers: H,
    body: JSON.stringify({ role: 'user', content: '一句话介绍你自己。' }),
  })
  const r = await fetch(`${BASE}/api/chat/conversations/${cid}/reply/stream`, {
    method: 'POST', headers: H,
    body: JSON.stringify({ context: '画布《先导预告片·画布》v1：节点 start（start）开始；gen（gen）生成预告片 [modality=video]；end（next）保存预告片' }),
  })
  console.log('HTTP', r.status, r.headers.get('content-type'))
  const dec = new TextDecoder()
  let buf = ''
  const reader = r.body.getReader()
  let n = 0
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
        if (ev.event === 'delta') { n++; if (n <= 3 || n % 40 === 0) process.stdout.write('[delta] ' + ev.text.slice(0, 60).replace(/\n/g, '\\n') + '\n') }
        else console.log('[' + ev.event + ']', JSON.stringify(ev).slice(0, 220))
      }
    }
  }
  console.log('total deltas:', n)
  const after = await (await fetch(`${BASE}/api/chat/conversations/${cid}`, { headers: H }).catch(() => null))
  // 会话详情接口可能没有；直接列消息验证落库
  const list = await (await fetch(`${BASE}/api/chat/conversations/list?scope_kind=global&scope_key=global`, { headers: H })).json()
  console.log('conversations:', list.length, 'latest preview:', list[0]?.preview?.slice(0, 40))
}
main().catch(e => { console.error('FAIL', e); process.exit(1) })
