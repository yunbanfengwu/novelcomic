import { useState, useRef, useCallback, useEffect } from 'react'
import type { VoiceSample } from '../../api'
import './EmotionSamples.css'

export function EmotionSamples({ samples }: { samples: VoiceSample[] }) {
  const [playing, setPlaying] = useState<VoiceSample | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const handleClick = useCallback((sample: VoiceSample) => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }

    if (playing?.emotion === sample.emotion) {
      setPlaying(null)
      return
    }

    const audio = new Audio(sample.url)
    audioRef.current = audio
    setPlaying(sample)

    audio.onended = () => {
      if (audioRef.current === audio) {
        setPlaying(null)
        audioRef.current = null
      }
    }

    audio.play().catch(() => {
      setPlaying(null)
      audioRef.current = null
    })
  }, [playing])

  useEffect(() => {
    return () => {
      audioRef.current?.pause()
      audioRef.current = null
    }
  }, [])

  if (!samples?.length) return null

  return (
    <div className={`emo-samples${playing ? ' playing' : ''}`}>
      <div className="emo-btns">
        {samples.map(s => (
          <button
            key={s.emotion}
            type="button"
            title={s.text}
            className={`emo-chip${playing?.emotion === s.emotion ? ' active' : ''}`}
            onClick={() => handleClick(s)}
          >
            <span className="emo-label">{s.emotion}</span>
            <div className="emo-wave">
              <span className="wave-bar" />
              <span className="wave-bar" />
              <span className="wave-bar" />
              <span className="wave-bar" />
              <span className="wave-bar" />
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
