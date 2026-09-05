import { Button } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { createClientId } from '../client-id'
import { useAppTheme } from '../app/AppThemeContext'
import { useI18n } from '../i18n'
import { MarkdownMessageContent } from '../agent/chat/MarkdownMessageContent'
import { projectDesktopContentParts } from '../agent/chat/projectDesktopContentParts'
import { createPreviewScript, initialPreviewParts, readPreviewFrame, type PreviewMode, type PreviewStep } from './messagePreviewScript'
import './process-transition.css'

interface Playback { steps: PreviewStep[]; started: number }

export function ProcessTransitionPreview() {
  const { t, toggleLocale } = useI18n()
  const { toggleTheme } = useAppTheme()
  const [preview, setPreview] = useState<{ parts: typeof initialPreviewParts; playback: Playback | null }>({ parts: initialPreviewParts, playback: null })
  const [narrow, setNarrow] = useState(false)
  const [resetKey, setResetKey] = useState(0)
  const { playback, parts } = preview
  const contentParts = useMemo(() => projectDesktopContentParts(parts), [parts])

  useEffect(() => {
    if (!playback) return
    const timer = window.setInterval(() => {
      const frame = readPreviewFrame(playback.steps, Date.now() - playback.started)
      setPreview((current) => {
        if (current.playback !== playback || (!frame.done && current.parts === frame.parts)) return current
        return { parts: frame.parts, playback: frame.done ? null : playback }
      })
    }, 70)
    return () => window.clearInterval(timer)
  }, [playback])

  const play = (mode: PreviewMode) => {
    const steps = createPreviewScript(mode, createClientId(), parts)
    setPreview({ parts: readPreviewFrame(steps, 0).parts, playback: { steps, started: Date.now() } })
    if (mode === 'sequence' || mode === 'first-token') setResetKey((value) => value + 1)
  }
  const reset = () => {
    setPreview({ parts: initialPreviewParts, playback: null })
    setResetKey((value) => value + 1)
  }
  const stop = () => setPreview((current) => ({ playback: null, parts: current.parts.map((part) => part.kind === 'tool_call' && part.title?.startsWith('正在')
    ? { ...part, title: t('transitionPreviewStopped'), metadata: { ...part.metadata, status: 'cancelled' } } : part) }))

  return <article className="transition-preview">
    <header className="transition-preview__header">
      <h1>{t('transitionPreviewTitle')}</h1>
      <p>{t('transitionPreviewHelp')}</p>
      <div className="transition-preview__controls">
        <Button type="primary" onClick={() => play('sequence')} disabled={Boolean(playback)}>{t('transitionPreviewFull')}</Button>
        <Button onClick={() => play('first-token')} disabled={Boolean(playback)}>{t('transitionPreviewFirstToken')}</Button>
        <Button onClick={() => play('tools')} disabled={Boolean(playback)}>{t('transitionPreviewTools')}</Button>
        <Button onClick={() => play('answer')} disabled={Boolean(playback)}>{t('transitionPreviewPlay')}</Button>
        {playback && <Button onClick={stop}>{t('transitionPreviewStop')}</Button>}
        <Button onClick={reset}>{t('transitionPreviewReset')}</Button>
        <Button onClick={() => setNarrow(!narrow)}>{t(narrow ? 'transitionPreviewWide' : 'transitionPreviewNarrow')}</Button>
        <Button onClick={toggleTheme}>{t('transitionPreviewTheme')}</Button>
        <Button onClick={toggleLocale}>{t('transitionPreviewLanguage')}</Button>
      </div>
    </header>
    <section className={`transition-preview__message${narrow ? ' transition-preview__message--narrow' : ''}`}>
      <MarkdownMessageContent key={resetKey} content="" contentParts={contentParts} enableProcessSession
        isMessageStreaming={Boolean(playback)} isProcessActive={Boolean(playback)} fontSize={14} />
    </section>
  </article>
}
