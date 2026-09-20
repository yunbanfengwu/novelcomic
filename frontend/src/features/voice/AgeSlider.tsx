import { useEffect, useState } from 'react'
import './AgeSlider.css'

/** 年龄滑块：拖动即时显示数字，松手才保存（onCommit）。音色库与角色卡共用。 */
export function AgeSlider({ value, onCommit, label = '年龄', disabled }: {
  value: number
  onCommit: (years: number) => void
  label?: string
  disabled?: boolean
}) {
  const [years, setYears] = useState(value)
  useEffect(() => { setYears(value) }, [value])

  return (
    <label className="age-slider">
      <span className="dim">{label}</span>
      <input type="range" min={1} max={100} value={years} disabled={disabled}
        onChange={e => setYears(Number(e.target.value))}
        onPointerUp={() => { if (years !== value) onCommit(years) }}
        onKeyUp={e => { if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && years !== value) onCommit(years) }} />
      <b className="age-slider-num">{years}岁</b>
    </label>
  )
}
