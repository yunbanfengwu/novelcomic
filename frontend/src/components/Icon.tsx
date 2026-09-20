import type { ReactNode } from 'react'
import './Icon.css'

// 统一线性图标集（stroke=currentColor，尺寸随 font-size；替代全站 emoji）。viewBox 0 0 24 24。
const ICONS: Record<string, ReactNode> = {
  book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v14H6.5A2.5 2.5 0 0 0 4 19.5z" /><path d="M20 17v4H6.5A2.5 2.5 0 0 1 4 18.5" /></>,
  gear: <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5 5l2.1 2.1M16.9 16.9L19 19M19 5l-2.1 2.1M7.1 16.9L5 19" /></>,
  clapper: <><rect x="3" y="8" width="18" height="12" rx="1.5" /><path d="M3 8l2.5-4 3.5 2M9 6l3.5-2 3.5 2M16 6l3.5-2 1 2.5M3 8h18" /></>,
  video: <><rect x="3" y="6" width="12.5" height="12" rx="2" /><path d="M15.5 10l5.5-3v10l-5.5-3z" /></>,
  menu: <><path d="M4 6.5h16M4 12h16M4 17.5h16" /></>,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6" /></>,
  image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9.5" r="1.6" /><path d="M4 18l5-5 4 3 3-3 4 4" /></>,
  palette: <><path d="M12 3a9 9 0 1 0 0 18c1.2 0 1.8-1.1 1.3-2.1-.5-1 .2-2.1 1.3-2.1H18a3 3 0 0 0 3-3 9 9 0 0 0-9-8.8z" /><circle cx="7.5" cy="11" r="1" /><circle cx="12" cy="7.5" r="1" /><circle cx="16.5" cy="11" r="1" /></>,
  tag: <><path d="M3 3h7.5L21 13.5 13.5 21 3 10.5z" /><circle cx="7.5" cy="7.5" r="1.4" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  lock: <><rect x="4.5" y="10.5" width="15" height="10" rx="2" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" /></>,
  clipboard: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1H9zM8 11h8M8 15h6" /></>,
  refresh: <path d="M20.5 12a8.5 8.5 0 1 1-2.4-6M20.5 3.5V9h-5.5" />,
  pencil: <><path d="M4 20h4L20 8a2.8 2.8 0 0 0-4-4L4 16z" /><path d="M14.5 5.5l4 4" /></>,
  alert: <><path d="M12 3.5 1.8 21h20.4z" /><path d="M12 10v5M12 17.6v.4" /></>,
  history: <><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3.5 4.5V10h5.5" /><path d="M12 7.5V12l3.2 2" /></>,
  scene: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8" cy="9" r="1.6" /><path d="M3 17l5-5 3 3 4-5 6 7" /></>,
  pen: <path d="M4 20l1-4L16 5l3 3L8 19z" />,
  clip: <path d="M20 11.5l-8.5 8.5a4.5 4.5 0 0 1-6.4-6.4L14 4.6a3 3 0 0 1 4.2 4.2l-8.6 8.6a1.5 1.5 0 0 1-2.1-2.1L14 8.4" />,
  sparkles: <><path d="M13.5 6.5l1.9 5 5.1 1.9-5.1 1.9-1.9 5.2-1.9-5.2-5.1-1.9 5.1-1.9z" /><path d="M6 2.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" /></>,
  robot: <><rect x="5" y="8" width="14" height="11" rx="2" /><path d="M12 8V4.5M9.5 4.5h5M3 12v3M21 12v3" /><circle cx="9.5" cy="13" r="1" /><circle cx="14.5" cy="13" r="1" /></>,
  save: <><path d="M5 4h11l3 3v13H5z" /><path d="M8 4v5h7V4M8 20v-6h8v6" /></>,
  external: <><path d="M13.5 4.5H19a.5.5 0 0 1 .5.5v5.5M19 5l-8.5 8.5" /><path d="M18 13.5v5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6h5" /></>,
  upload: <><path d="M12 15V4M8 8l4-4 4 4" /><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" /></>,
  folder: <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5z" />,
  folderplus: <><path d="M3 9A2 2 0 0 1 5 7h3.2l1.8 2.3H15A2 2 0 0 1 17 11.3V17A2 2 0 0 1 15 19H5a2 2 0 0 1-2-2z" /><path d="M18.5 4v4.4M16.3 6.2h4.4" /></>,
  speaker: <><path d="M4 9v6h4l5 4V5L8 9z" /><path d="M16.5 9.5a3.5 3.5 0 0 1 0 5M19 7a7 7 0 0 1 0 10" /></>,
  mute: <><path d="M4 9v6h4l5 4V5L8 9z" /><path d="M16.5 9.5l4.5 4.5M21 9.5L16.5 14" /></>,
  ruler: <><path d="M4 4v16h16z" /><path d="M4 9h4M4 14h9" /></>,
  puzzle: <path d="M10 4a2 2 0 1 1 4 0v1h3a1 1 0 0 1 1 1v3h1a2 2 0 1 1 0 4h-1v3a1 1 0 0 1-1 1h-3v-1a2 2 0 1 0-4 0v1H7a1 1 0 0 1-1-1v-3H5a2 2 0 1 1 0-4h1V6a1 1 0 0 1 1-1h3z" />,
  check: <><circle cx="12" cy="12" r="9" /><path d="M8 12.5l2.8 2.8L16.5 9" /></>,
  warn: <><path d="M12 3.5l9 15.5H3z" /><path d="M12 10v4M12 16.8h.01" /></>,
  cross: <><circle cx="12" cy="12" r="9" /><path d="M9 9l6 6M15 9l-6 6" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" /></>,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M3 20a6 6 0 0 1 12 0M16 4.7a3.5 3.5 0 0 1 0 6.6M21 20a6 6 0 0 0-4-5.7" /></>,
  camera: <><rect x="3" y="7" width="18" height="13" rx="2" /><circle cx="12" cy="13.5" r="3.4" /><path d="M8 7l1.5-2.5h5L16 7" /></>,
  motion: <><circle cx="13" cy="4.5" r="2" /><path d="M13 7l-1.5 4 3 1.5 1 5.5M11.5 11L7 10M14.5 12.5l3-1" /></>,
  blocks: <><path d="M4 5h5v14H4z" /><path d="M9 5h5v14H9z" /><path d="M14 6.5l4-1 2.5 13.5-4 1z" /></>,
  tools: <path d="M15 6a4 4 0 0 1-5.2 5.2l-6 6 2 2 6-6A4 4 0 0 1 17 8l-2.2 2.2-1-1L16 7z" />,
  workflow: <><rect x="3" y="4" width="6" height="5" rx="1.2" /><rect x="15" y="15" width="6" height="5" rx="1.2" /><path d="M9 6.5h3a3 3 0 0 1 3 3v3a3 3 0 0 0 3 3M12 13l3 2.5-3 2.5" /></>,
  node: <><circle cx="7.5" cy="5.5" r="2.5" /><circle cx="16.5" cy="5.5" r="2.5" /><circle cx="12" cy="18.5" r="2.5" /><path d="M7.5 8v1.5a2 2 0 0 0 2 2h5a2 2 0 0 0 2-2V8M12 11.5V16" /></>,
  text: <><rect x="5" y="3.5" width="14" height="17" rx="2" /><path d="M8 8.5h8M8 12h8M8 15.5h5" /></>,
  flask: <><path d="M9 3h6M10 3v6l-5.2 9A2 2 0 0 0 6.5 21h11a2 2 0 0 0 1.7-3l-5.2-9V3" /><path d="M7.5 14.5h9" /></>,
  link: <path d="M9 15l6-6M8.5 11.5l-2 2a3.2 3.2 0 0 0 4.5 4.5l2-2M15.5 12.5l2-2a3.2 3.2 0 0 0-4.5-4.5l-2 2" />,
  unlink: <><path d="M8.5 11.5l-2 2a3.2 3.2 0 0 0 4.5 4.5l2-2M15.5 12.5l2-2a3.2 3.2 0 0 0-4.5-4.5l-2 2" /><path d="M5 4l15 15" /></>,
  person: <><circle cx="12" cy="5" r="2.5" /><path d="M12 8v8M12 16l-2.5 5M12 16l2.5 5" /></>,
  compass: <><circle cx="12" cy="12" r="9" /><path d="M15.5 8.5l-2.2 4.8-4.8 2.2 2.2-4.8z" /></>,
  monitor: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M9 20h6M12 16v4" /></>,
  phone: <><rect x="7" y="3" width="10" height="18" rx="2" /><path d="M11 18h2" /></>,
  pin: <path d="M12 21v-7M8 3h8l-1.2 5.2L18 11H6l3.2-2.8z" />,
  wand: <><path d="M14.5 4.2l5.3 5.3M13.5 5.2l1-1 5.3 5.3-1 1zM11 9L4 16v4h4l7-7" /><path d="M5.5 3.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" /></>,
  rocket: <><path d="M12 3c3 2.2 4.8 6 4.8 10L15 15H9l-1.8-2c0-4 1.8-7.8 4.8-10z" /><circle cx="12" cy="10.5" r="1.8" /><path d="M7.5 16l-2 4 4-1.8M16.5 16l2 4-4-1.8" /></>,
  drama: <><path d="M4 5h7v4.5a3.5 3.5 0 0 1-7 0zM4.5 11a3 3 0 0 0 6 0" /><path d="M13 8h7v4.5a3.5 3.5 0 0 1-7 0zM13.5 14a3 3 0 0 0 6 0" /></>,
  chat: <path d="M4 5h16v11H9l-4 3.5V16H4z" />,
  cut: <><circle cx="6" cy="6.5" r="2.5" /><circle cx="6" cy="17.5" r="2.5" /><path d="M8.2 7.5L20 17M8.2 16.5L20 7" /></>,
  web: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="4.5" /><path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" /></>,
  conflict: <><path d="M4.5 3.5l9 9-2 2-9-9v-2zM3 17.5l4 4" /><path d="M19.5 3.5l-9 9 2 2 9-9v-2zM21 17.5l-4 4" /></>,
  hook: <path d="M13 3v10.5a3.5 3.5 0 1 1-3.5-3.5M11 3h4" />,
  scroll: <><path d="M7 5h10v11.5a2.5 2.5 0 0 0 2.5 2.5H8.5A2.5 2.5 0 0 1 6 16.5V6" /><path d="M6 5a2 2 0 0 0-2 2h3" /><path d="M9.5 9h5M9.5 12.5h5" /></>,
  spinner: <path d="M12 3a9 9 0 1 0 9 9" />,
  home: <path d="M4 11l8-7 8 7M6 9.5V20h12V9.5" />,
  play: <path d="M7 4.5l12 7.5-12 7.5z" fill="currentColor" stroke="none" />,
  // 运行管理：三角 + 右下角时钟角标（区别于「直接运行」那枚纯三角）。
  // 角标**压在三角右下角上**（环线穿过实心三角），是一枚合成图标而不是并排两个；
  // 表针落在三角轮廓之外，压着也认得出是钟。
  playclock: <><path d="M6 3.8l9.6 6.1-9.6 6.1z" fill="currentColor" stroke="none" /><circle cx="17.2" cy="17.2" r="4.4" /><path d="M17.2 15.1v2.1l1.5 1.1" /></>,
  loop: <><path d="M7 7.5h9.5l-2.8-2.8M17 16.5H7.5l2.8 2.8" /><path d="M16.5 7.5A6.5 6.5 0 0 1 19 12a6.5 6.5 0 0 1-2 4.6M7.5 16.5A6.5 6.5 0 0 1 5 12a6.5 6.5 0 0 1 2-4.6" /></>,
  pause: <><rect x="7" y="5" width="3.4" height="14" rx="1" fill="currentColor" stroke="none" /><rect x="13.6" y="5" width="3.4" height="14" rx="1" fill="currentColor" stroke="none" /></>,
  playnext: <><path d="M5 5l9 7-9 7z" fill="currentColor" stroke="none" /><rect x="16.5" y="5" width="2.8" height="14" rx="1" fill="currentColor" stroke="none" /></>,
  search: <><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5L20.5 20.5" /></>,
  fullscreen: <path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4" />,
  queue: <><path d="M4 5.5h16M4 11h9M4 16.5h7" /><circle cx="17" cy="16" r="4" /><path d="M17 14.2v1.8l1.4 1" /></>,
  collapse: <path d="M9 4v3a1 1 0 0 1-1 1H5M15 4v3a1 1 0 0 0 1 1h3M9 20v-3a1 1 0 0 0-1-1H5M15 20v-3a1 1 0 0 1 1-1h3" />,
  more: <><circle cx="12" cy="5" r="1.6" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" /><circle cx="12" cy="19" r="1.6" fill="currentColor" stroke="none" /></>,
  zap: <path d="M13 2.5L4.5 13.5H11l-1 8L19.5 10.5H13z" />,
  console: <><path d="M4 6.5h8M16 6.5h4" /><circle cx="14" cy="6.5" r="2" /><path d="M4 12h3M11 12h9" /><circle cx="9" cy="12" r="2" /><path d="M4 17.5h8M16 17.5h4" /><circle cx="14" cy="17.5" r="2" /></>,
  trash: <><path d="M4 6.5h16M9 6.5V4.5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /><path d="M6 6.5l1 13a1.5 1.5 0 0 0 1.5 1.4h7A1.5 1.5 0 0 0 17 19.5l1-13" /><path d="M10 10.5v6M14 10.5v6" /></>,
  undo: <path d="M4 9h9a5.5 5.5 0 0 1 0 11h-3M4 9l4-4M4 9l4 4" />,
  back: <path d="M11 5l-7 7 7 7M4 12h16" />,
  wallet: <><path d="M4 7a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v2" /><path d="M4 7v10a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-3M4 7h15a1 1 0 0 1 1 1v4h-4a2 2 0 0 1 0-4h4" /><circle cx="16" cy="12" r=".9" fill="currentColor" stroke="none" /></>,
  idcard: <><rect x="3" y="5" width="18" height="14" rx="2" /><circle cx="8.5" cy="11" r="2.2" /><path d="M5 16a3.5 3.5 0 0 1 7 0M14 9.5h4M14 13h3" /></>,
  crop: <path d="M7 3v14h14M3 7h14v14" />,
  cube: <><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" /><path d="M4 7.5l8 4.5 8-4.5M12 12v9" /></>,
  eraser: <><path d="M4 15.5l8.5-8.5a2 2 0 0 1 2.8 0l3.7 3.7a2 2 0 0 1 0 2.8L13.5 19H8z" /><path d="M8 19h13" /></>,
  download: <><path d="M12 4v11M7.5 11l4.5 4.5L16.5 11" /><path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" /></>,
  layers: <><path d="M12 3l9 5-9 5-9-5z" /><path d="M3.5 12.5L12 17l8.5-4.5M3.5 17L12 21.5 20.5 17" /></>,
  grid: <><rect x="4" y="4" width="16" height="16" rx="1.5" /><path d="M4 12h16M12 4v16" /></>,
  ungroup: <><rect x="3.5" y="3.5" width="8" height="8" rx="1.5" /><rect x="12.5" y="12.5" width="8" height="8" rx="1.5" /><path d="M15 6.5h2.5M6.5 15v2.5" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.2a2.6 2.6 0 1 1 3.6 2.5c-.8.4-1.1 1-1.1 1.8v.3" /><path d="M12 17.2v.05" /></>,
  bell: <><path d="M12 4a5.5 5.5 0 0 1 5.5 5.5c0 3.7 1 5 2 6H4.5c1-1 2-2.3 2-6A5.5 5.5 0 0 1 12 4z" /><path d="M10 19a2 2 0 0 0 4 0" /></>,
  share: <><circle cx="6" cy="12" r="2.5" /><circle cx="17.5" cy="5.5" r="2.5" /><circle cx="17.5" cy="18.5" r="2.5" /><path d="M8.3 10.8l7-4M8.3 13.2l7 4" /></>,
  arrowup: <path d="M12 19V6M6 11.5L12 5.5l6 6" />,
  focus: <><circle cx="12" cy="12" r="3.5" /><path d="M12 3v3.5M12 17.5V21M3 12h3.5M17.5 12H21" /></>,
  zoomin: <><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5L20.5 20.5M8.5 11h5M11 8.5v5" /></>,
  zoomout: <><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5L20.5 20.5M8.5 11h5" /></>,
  // 纸飞机（发送/智能生成）：实心小飞机，尖朝右上
  send: <path d="M3.4 20.4l17.8-8.4L3.4 3.6l-.02 6.53L14 12 3.38 13.87z" fill="currentColor" stroke="none" />,
}

export type IconName = keyof typeof ICONS

/** 内联 SVG 图标：尺寸随 font-size，颜色随 currentColor。spin=旋转（加载态）。 */
export function Icon({ name, className, spin }: { name: IconName; className?: string; spin?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" stroke="currentColor"
      strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      className={'icon' + (spin ? ' icon-spin' : '') + (className ? ' ' + className : '')}>
      {ICONS[name]}
    </svg>
  )
}
