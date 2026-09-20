import { newTapNode, type TapEdge, type TapNode, type TapParam } from './tapflowData'

export interface LoopWrapResult {
  loop: TapNode
  nodes: TapNode[]
  edges: TapEdge[]
}

/**
 * Turn a selected downstream subgraph into a real workflow loop.
 *
 * The body remains visible on the canvas, but loop.body is persisted in the
 * backend graph. External inputs are redirected to the loop controller and
 * entry nodes receive an `each` edge; body outputs keep `collect` edges so a
 * following node can opt into aggregate semantics.
 */
export function wrapSelectionInLoop(
  nodes: TapNode[], edges: TapEdge[], ids: string[], x: number, y: number,
): LoopWrapResult | null {
  const selected = new Set(ids)
  const bodyCandidates = nodes.filter(n => selected.has(n.id)
    && n.type !== 'start' && n.type !== 'loop' && n.type !== 'mount')
  if (bodyCandidates.length < 1) return null

  // Stable topological order for the loop runner. The backend deliberately
  // executes body ids in this order rather than trying to re-run the outer DAG.
  const bodySet = new Set(bodyCandidates.map(n => n.id))
  const bodyEdges = edges.filter(e => bodySet.has(e.from) && bodySet.has(e.to))
  const indegree = new Map(bodyCandidates.map(n => [n.id, 0]))
  const next = new Map(bodyCandidates.map(n => [n.id, [] as string[]]))
  for (const edge of bodyEdges) {
    indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1)
    next.get(edge.from)?.push(edge.to)
  }
  const ready = bodyCandidates.filter(n => indegree.get(n.id) === 0).map(n => n.id)
  const body: string[] = []
  while (ready.length) {
    const id = ready.shift()!
    body.push(id)
    for (const to of next.get(id) ?? []) {
      const left = (indegree.get(to) ?? 1) - 1
      indegree.set(to, left)
      if (left === 0) ready.push(to)
    }
  }
  // A selected cycle cannot be made valid by adding a loop controller.
  if (body.length !== bodyCandidates.length) return null

  const externalIn = edges.filter(e => !selected.has(e.from) && selected.has(e.to))
  // bodyEdges has only selected endpoints, so derive entries from the absence of
  // an internal predecessor instead.
  const internalTargets = new Set(bodyEdges.map(e => e.to))
  const entries = body.filter(id => !internalTargets.has(id))

  const sourceCandidates: Array<{ source: string; field: TapParam }> = []
  for (const edge of externalIn) {
    const source = nodes.find(n => n.id === edge.from)
    for (const field of source?.outputs ?? (source?.type === 'start' ? source.params ?? [] : [])) {
      sourceCandidates.push({ source: edge.from, field })
    }
  }
  const preferred = sourceCandidates.find(x => x.field.k === 'descriptors')
    ?? sourceCandidates.find(x => x.field.itemFields?.length)
    ?? sourceCandidates.find(x => x.field.type === 'json')
    ?? sourceCandidates[0]
  const sourceToken = preferred
    ? `{{${preferred.source === 'start' ? 'input' : preferred.source}.${preferred.field.k}}}`
    : ''
  const itemFields = preferred?.field.itemFields

  const loop = newTapNode('loop', x, y)
  loop.title = '循环'
  loop.loop = {
    aggregate: true,
    source: sourceToken,
    body,
    concurrency: 1,
    itemFields,
    actionTitle: `循环执行 ${body.length} 个节点`,
  }
  loop.outputs = [
    { k: 'results', label: '循环结果', type: 'json', v: '' },
    { k: 'count', label: '循环次数', type: 'int', v: '' },
    { k: 'failed', label: '失败数量', type: 'int', v: '' },
  ]

  const edgeKey = (edge: Pick<TapEdge, 'from' | 'to'>) => `${edge.from}->${edge.to}`
  const seen = new Set<string>()
  const out: TapEdge[] = []
  const push = (edge: TapEdge) => {
    const key = edgeKey(edge)
    if (seen.has(key)) return
    seen.add(key)
    out.push(edge)
  }
  for (const edge of edges) {
    // External edges now enter the loop controller, while internal edges remain
    // body edges. Outbound edges collect the loop's per-item product.
    if (!selected.has(edge.from) && selected.has(edge.to)) continue
    if (selected.has(edge.from) && !selected.has(edge.to)) {
      push({ ...edge, mapping: 'collect' })
      continue
    }
    push(edge)
  }
  for (const edge of externalIn) push({ id: `e-${edge.from}-${loop.id}`, from: edge.from, to: loop.id })
  for (const entry of entries) push({ id: `e-${loop.id}-${entry}`, from: loop.id, to: entry, mapping: 'each' })

  return { loop, nodes: [...nodes, loop], edges: out }
}
