// 扫描前端源码中的关键词（Esafenet 下 bash grep 不可靠，用 node fs）
const fs = require('fs')
const path = require('path')
const hits = []
function walk(d) {
  for (const f of fs.readdirSync(d)) {
    const p = path.join(d, f)
    const st = fs.statSync(p)
    if (st.isDirectory()) walk(p)
    else if (/\.(tsx?|css)$/.test(f)) {
      const t = fs.readFileSync(p, 'utf8')
      for (const kw of ['已执行', '个任务', '查看画布', 'TapNow', '单节点运行']) {
        if (t.includes(kw)) hits.push(p.replace(/\\/g, '/') + ' | ' + kw)
      }
    }
  }
}
walk(path.resolve(__dirname, '..', '..', 'frontend', 'src'))
console.log(hits.join('\n') || 'no hits')
