/** Lightbox 右侧信息面板的通用文块：分节的「标签 + 文本」（空文本节自动跳过）。 */
export function LightboxInfo({ sections }: {
  sections: { label?: string; text?: string }[]
}) {
  return (
    <div className="lb-info">
      {sections.filter(s => s.text).map((s, i) => (
        <div key={i}>
          {s.label && <div className="lb-label">{s.label}</div>}
          <div className="lb-text">{s.text}</div>
        </div>
      ))}
    </div>
  )
}
