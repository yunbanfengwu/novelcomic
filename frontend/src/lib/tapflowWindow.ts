import type { WorkflowSubject } from '../api'
import type { TapFlowMeta } from './tapflowData'

/** Payload kept briefly in same-origin storage while a Tapflow window starts. */
export type TapflowWindowPayload = {
  slug?: string
  /** Studio saves a published workflow as a draft version; keep that exact version across refreshes. */
  version?: number
  variant: 'studio' | 'production'
  inputs?: Record<string, string | number>
  subject?: WorkflowSubject
  /** Local demo flows do not have a backend slug, so pass their canvas directly. */
  flow?: TapFlowMeta
  /** 入口业务对象的**当前产物**（如项目现有封面）：归宿挂载点进画布即回显它，
   * 不用等下一次运行。只是显示——落库状态仍以挂载点自己的运行回显为准 */
  productUrl?: string
}

export const TAPFLOW_WINDOW_MESSAGE = 'novelcomic:tapflow-window-closed'

const STORAGE_PREFIX = 'novelcomic:tapflow-window:'

function newRequestId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

/**
 * Open the canvas from a user gesture. The state is stored before window.open so
 * even a large demo graph does not need to be put in the URL.
 */
export function openTapflowWindow(payload: TapflowWindowPayload): string | null {
  const requestId = newRequestId()
  const storageKey = `${STORAGE_PREFIX}${requestId}`
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(payload))
  } catch {
    return null
  }

  const url = new URL('/tapflow/window', window.location.href)
  url.searchParams.set('state', requestId)
  // Keep the business context visible in the navigation as well as in storage.
  // The state token is still needed for demo graphs and for lossless values.
  if (payload.slug) url.searchParams.set('slug', payload.slug)
  if (payload.version !== undefined) url.searchParams.set('version', String(payload.version))
  url.searchParams.set('variant', payload.variant)
  for (const [key, value] of Object.entries(payload.inputs ?? {})) {
    url.searchParams.set(key, String(value))
  }
  if (payload.subject) {
    url.searchParams.set('subject_kind', payload.subject.kind)
    url.searchParams.set('subject_id', String(payload.subject.id))
    if (payload.subject.name) url.searchParams.set('subject_name', payload.subject.name)
    if (payload.subject.canvasRole) url.searchParams.set('canvas_role', payload.subject.canvasRole)
  }
  if (payload.productUrl) url.searchParams.set('product_url', payload.productUrl)
  // `_blank` asks the browser for a new tab. Do not pass popup/window features:
  // browsers interpret those features as a request for a separate window.
  const child = window.open(url.toString(), '_blank')
  if (!child) {
    window.localStorage.removeItem(storageKey)
    return null
  }
  child.focus()
  return requestId
}

/** Recover a production launch when a copied/shared URL has no storage token. */
export function readTapflowWindowLocation(search: string): TapflowWindowPayload | null {
  const params = new URLSearchParams(search)
  const variant = params.get('variant')
  if (variant !== 'studio' && variant !== 'production') return null
  const slug = params.get('slug') ?? undefined
  if (!slug) return null
  const reserved = new Set([
    'state', 'slug', 'version', 'variant', 'subject_kind', 'subject_id', 'subject_name',
    'canvas_role', 'product_url',
  ])
  const inputs: Record<string, string> = {}
  for (const [key, value] of params.entries()) {
    if (!reserved.has(key)) inputs[key] = value
  }
  const subjectKind = params.get('subject_kind')
  const subjectId = Number(params.get('subject_id'))
  const subject = subjectKind && Number.isFinite(subjectId)
    ? {
        kind: subjectKind,
        id: subjectId,
        name: params.get('subject_name') ?? undefined,
        canvasRole: params.get('canvas_role') ?? undefined,
      }
    : undefined
  const rawVersion = Number(params.get('version'))
  const version = Number.isInteger(rawVersion) && rawVersion > 0 ? rawVersion : undefined
  const productUrl = params.get('product_url') ?? undefined
  return { slug, version, variant, inputs, subject, productUrl }
}

export function readTapflowWindowState(requestId: string): TapflowWindowPayload | null {
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${requestId}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as TapflowWindowPayload
    if (!parsed || (parsed.variant !== 'studio' && parsed.variant !== 'production')) return null
    return parsed
  } catch {
    return null
  }
}

export function isTapflowWindowClosedMessage(event: MessageEvent, requestId: string): boolean {
  return event.origin === window.location.origin
    && event.data?.type === TAPFLOW_WINDOW_MESSAGE
    && event.data?.requestId === requestId
}

export function notifyTapflowWindowClosed(requestId: string) {
  if (window.opener && !window.opener.closed) {
    window.opener.postMessage({ type: TAPFLOW_WINDOW_MESSAGE, requestId }, window.location.origin)
  }
  try {
    window.localStorage.removeItem(`${STORAGE_PREFIX}${requestId}`)
  } catch {
    // Storage can be unavailable in privacy-restricted windows; closing still works.
  }
}
