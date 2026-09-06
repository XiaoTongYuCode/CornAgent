import { Button } from 'antd'
import { Languages, Moon, Pause, Play, RotateCcw, Sun } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { createClientId } from '../client-id'
import { useAppTheme } from '../app/AppThemeContext'
import { useI18n } from '../i18n'
import { MarkdownMessageContent } from '../agent/chat/MarkdownMessageContent'
import { projectDesktopContentParts } from '../agent/chat/projectDesktopContentParts'
import { createPreviewScript, initialPreviewParts, readPreviewFrame, type PreviewMode, type PreviewStep } from './messagePreviewScript'
import './process-transition.css'

interface Playback { steps: PreviewStep[]; elapsed: number; resumedAt: number | null }
const iconProps = { size: 16, strokeWidth: 1.75, 'aria-hidden': true } as const

export function ProcessTransitionPreview() {
  const { locale, t, toggleLocale } = useI18n()
  const { theme, toggleTheme } = useAppTheme()
  const [preview, setPreview] = useState<{ parts: typeof initialPreviewParts; playback: Playback | null }>({ parts: initialPreviewParts, playback: null })
  const [resetKey, setResetKey] = useState(0)
  const { playback, parts } = preview
  const isPlaying = playback !== null && playback.resumedAt !== null
  const isPaused = playback !== null && playback.resumedAt === null
  const contentParts = useMemo(() => projectDesktopContentParts(parts[locale]), [parts, locale])

  useEffect(() => {
    if (!playback || playback.resumedAt === null) return
    const { resumedAt } = playback
    const timer = window.setInterval(() => {
      const frame = readPreviewFrame(playback.steps, playback.elapsed + Date.now() - resumedAt)
      setPreview((current) => {
        if (current.playback !== playback || (!frame.done && current.parts === frame.parts)) return current
        return { parts: frame.parts, playback: frame.done ? null : playback }
      })
    }, 70)
    return () => window.clearInterval(timer)
  }, [playback])

  const play = (mode: PreviewMode) => {
    const steps = createPreviewScript(mode, createClientId(), parts)
    setPreview({ parts: readPreviewFrame(steps, 0).parts, playback: { steps, elapsed: 0, resumedAt: Date.now() } })
    if (mode === 'sequence' || mode === 'first-token' || mode === 'tool-group') setResetKey((value) => value + 1)
  }
  const reset = () => {
    setPreview({ parts: initialPreviewParts, playback: null })
    setResetKey((value) => value + 1)
  }
  const togglePlayback = () => {
    if (!playback) {
      play('sequence')
      return
    }
    const now = Date.now()
    setPreview((current) => {
      const active = current.playback
      if (!active) return current
      if (active.resumedAt === null) return { ...current, playback: { ...active, resumedAt: now } }
      const elapsed = active.elapsed + now - active.resumedAt
      const frame = readPreviewFrame(active.steps, elapsed)
      return { parts: frame.parts, playback: frame.done ? null : { ...active, elapsed, resumedAt: null } }
    })
  }

  return <article className={`transition-preview${isPaused ? ' transition-preview--paused' : ''}`}>
    <header className="transition-preview__header">
      <h1>{t('transitionPreviewTitle')}</h1>
      <p>{t('transitionPreviewHelp')}</p>
      <div className="transition-preview__controls">
        <div className="transition-preview__toolbar">
          <div role="group" aria-label={t('transitionPreviewPlayback')}>
            <Button className="transition-preview__playback" type="primary" onClick={togglePlayback}
              icon={isPlaying ? <Pause {...iconProps} /> : <Play {...iconProps} />}>
              {t(isPlaying ? 'transitionPreviewPause' : isPaused ? 'transitionPreviewResume' : 'transitionPreviewFull')}
            </Button>
          </div>
          <div className="transition-preview__settings" role="group" aria-label={t('transitionPreviewSettings')}>
            <Button type="text" onClick={reset} icon={<RotateCcw {...iconProps} />}
              aria-label={t('transitionPreviewReset')} title={t('transitionPreviewReset')} />
            <Button type="text" onClick={toggleLocale} icon={<Languages {...iconProps} />}
              aria-label={t('transitionPreviewLanguage')} title={t('transitionPreviewLanguage')} />
            <Button type="text" onClick={toggleTheme} icon={theme === 'dark' ? <Sun {...iconProps} /> : <Moon {...iconProps} />}
              aria-label={t('transitionPreviewTheme')} title={t('transitionPreviewTheme')} />
          </div>
        </div>
        <div className="transition-preview__scenarios" role="group" aria-label={t('transitionPreviewScenarios')}>
          <Button onClick={() => play('first-token')} disabled={Boolean(playback)}>{t('transitionPreviewFirstToken')}</Button>
          <Button onClick={() => play('tools')} disabled={Boolean(playback)}>{t('transitionPreviewTools')}</Button>
          <Button onClick={() => play('answer')} disabled={Boolean(playback)}>{t('transitionPreviewPlay')}</Button>
          <Button onClick={() => play('tool-group')} disabled={Boolean(playback)}>{t('transitionPreviewToolGroup')}</Button>
        </div>
      </div>
    </header>
    <section className="transition-preview__message" aria-label={t('transitionPreviewTitle')} tabIndex={0}>
      <MarkdownMessageContent key={resetKey} content="" contentParts={contentParts} enableProcessSession
        isMessageStreaming={Boolean(playback)} isProcessActive={Boolean(playback)} fontSize={14} />
    </section>
  </article>
}
