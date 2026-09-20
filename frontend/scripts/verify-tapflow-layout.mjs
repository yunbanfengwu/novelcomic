// tapflow 布局规则校验（node scripts/verify-tapflow-layout.mjs）：
// 用 esbuild 把 src/lib/tapflowLayout.ts 打成可加载模块，对布局结果断言——
//   1. 开始节点独占最左一条列线（第一列只有它）；
//   2. 其余内容节点一律在开始列之后；
//   3. 结束节点（无出边）独占最后一条列线（最后一列只有它们）；
//   4. 列号不设下限：负列（开始列以左）也落位，不弹回第 0 列；
//   5. 列距 = COLUMN_STEP（辅助线间隔），行距不小于 ROW_GAP。
// 这是「整理画布」与「向两边无限扩展」的回归线：改布局逻辑后必须跑它。
import ts from 'typescript'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const outDir = mkdtempSync(tmpdir() + '/tapflow-layout-')
// tapflowLayout 对 tapflowData 只有 import type（类型擦除后零依赖），单文件转译即可加载
const js = ts.transpileModule(readFileSync('src/lib/tapflowLayout.ts', 'utf8'), {
  compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  },
}).outputText
writeFileSync(join(outDir, 'layout.mjs'), js)
const mod = await import(pathToFileURL(join(outDir, 'layout.mjs')).href)
const { layoutPositions, snapColumnX, COLUMN_STEP, ROW_GAP, LAYOUT_MARGIN, COLUMN_WIDTH } = mod
rmSync(outDir, { recursive: true, force: true })

const node = (id, type, x, y, w = 460, h = 273) => ({ id, type, title: id, x, y, w, h })
let failed = 0
const check = (name, ok) => {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`)
  if (!ok) failed++
}

// 场景 A：真实产线形态——开始 → 文本 → 出图 → 挂载点，另一条短链 start→review(无出边)
{
  const nodes = [
    node('start', 'start', 0, 0, 560, 460),
    node('brief', 'text', 660, 0, 460, 280),
    node('gen', 'gen', 1320, 0),
    node('mount', 'mount', 1980, 0, 690, 410),
    node('review', 'text', 660, 800, 460, 280),   // 短支路的终点（无出边）
    node('up', 'upload', 40, -600, 460, 273),      // 无出边的上传素材（也是终点）
  ]
  const edges = [
    { from: 'start', to: 'brief' }, { from: 'brief', to: 'gen' },
    { from: 'gen', to: 'mount' },
  ]
  const pos = layoutPositions(nodes, edges)
  // 列中心 = x + w/2：列号只看中心，不能比原始 x（窄卡在列内的偏移不同）
  const cx = id => pos.get(id).x + nodes.find(m => m.id === id).w / 2
  const xs = id => pos.get(id).x

  check('开始节点存在且落在最左列', pos.has('start') && ['brief', 'gen', 'mount', 'review', 'up'].every(id => cx(id) > cx('start')))
  check('开始列只有开始节点（独占一条线）', ['brief', 'gen', 'mount', 'review', 'up'].every(id => xs(id) !== xs('start')))
  check('其余节点都在开始列之后（往后排）', ['brief', 'gen'].every(id => cx(id) > cx('start')))
  check('结束节点全部排在最右一条独立列线上', ['mount', 'review', 'up'].every(id => Math.abs(cx(id) - cx('mount')) < 0.01) && cx('mount') > cx('gen') && cx('mount') > cx('brief'))
  check('列距按 COLUMN_STEP 铺开（不再拥挤）', xs('gen') - xs('brief') >= COLUMN_STEP - 1)
}

// 场景 B：无出边的环上节点不误判为终点；纯链式图的终点是挂载点
{
  const nodes = [node('start', 'start', 0, 0, 560, 460), node('a', 'gen', 660, 0), node('end1', 'mount', 1320, 0, 690, 410)]
  const edges = [{ from: 'start', to: 'a' }, { from: 'a', to: 'end1' }]
  const pos = layoutPositions(nodes, edges)
  const xs = id => pos.get(id).x
  check('三节链：开始 < 过程 < 结束，各占一列', xs('start') < xs('a') && xs('a') < xs('end1'))
}

// 场景 C：负列吸附——模拟「拖到开始列以左」松手，列号不设下限、不弹回第 0 列
{
  // 第 0 列中心 = LAYOUT_MARGIN + COLUMN_WIDTH/2；往左 3 列的中心应吸到 -3 列
  const colCenter0 = LAYOUT_MARGIN + COLUMN_WIDTH / 2
  const x = snapColumnX(colCenter0 - 3 * COLUMN_STEP + 137, 460)
  const colBack = Math.round((x + 460 / 2 - colCenter0) / COLUMN_STEP)
  check('吸附到负列：第 0 列以左有落点', x < LAYOUT_MARGIN && colBack === -3)
  // 吸完后节点中心恰落在列线上；再吸一次位置不变（幂等），±20px 抖动也归到同一列
  const once = snapColumnX(colCenter0, 460)
  check('吸附幂等：吸完的中心再吸不动', once + 460 / 2 === colCenter0 && snapColumnX(once + 460 / 2, 460) === once && snapColumnX(colCenter0 + 20, 460) === once)
}

// 场景 D：列距规则——开始独占一列后内容整体右移；相邻内容列中心距恰为 COLUMN_STEP
{
  const nodes = [node('start', 'start', 0, 0, 560, 460), node('a', 'gen', 660, 0), node('b', 'mount', 1320, 0, 690, 410)]
  const pos = layoutPositions(nodes, [{ from: 'start', to: 'a' }, { from: 'a', to: 'b' }])
  const cx = id => pos.get(id).x + nodes.find(m => m.id === id).w / 2
  check('开始列到首条内容列：独占 + 一列呼吸位（2×STEP）', Math.abs((cx('a') - cx('start')) - 2 * COLUMN_STEP) < 0.01)
  check('相邻内容列中心距 = COLUMN_STEP（辅助线间隔与列对齐）', Math.abs((cx('b') - cx('a')) - COLUMN_STEP) < 0.01)
  check('行距常量已放宽（≥96）', ROW_GAP >= 96)
}

console.log(failed ? `\n${failed} 项未通过` : '\n全部通过')
process.exit(failed ? 1 : 0)
