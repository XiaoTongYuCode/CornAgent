import type { AgentContentPart } from '../agent/types'
import type { Locale } from '../i18n'
import { messagePreviewCopy } from './messagePreviewCopy'

export type PreviewMode = 'sequence' | 'first-token' | 'tools' | 'answer' | 'tool-group'
export type PreviewParts = Record<Locale, AgentContentPart[]>
export interface PreviewStep { duration: number; parts: PreviewParts; streamId?: string }

const forLocales = <T,>(create: (locale: Locale) => T): Record<Locale, T> => ({ 'zh-CN': create('zh-CN'), en: create('en') })
export const initialPreviewParts: PreviewParts = forLocales((locale) => {
  const copy = messagePreviewCopy[locale]
  return [
    { id: 'reasoning-1', kind: 'reasoning', content: copy.initialReasoning },
    { id: 'question-1', kind: 'user_question', content: '', metadata: { status: 'answered', answer_content: copy.questionAnswer, selected_option_id: 'demo' } },
    { id: 'body-1', kind: 'markdown', content: copy.initialBody },
    { id: 'tool-1', kind: 'tool_call', title: copy.readDone, content: copy.initialToolResult },
    { id: 'wait-1', kind: 'tool_call', content: '', metadata: { tool_name: 'wait_subagents', task_count: 3, status: 'completed' } },
  ]
})

/** Deterministic presentation frames; no transport, model, or persisted session. */
export function createPreviewScript(mode: PreviewMode, prefix: string, existing: PreviewParts): PreviewStep[] {
  const steps: PreviewStep[] = []
  let parts = mode === 'sequence' || mode === 'first-token' || mode === 'tool-group' ? forLocales<AgentContentPart[]>(() => []) : existing
  const append = (createPart: (locale: Locale) => AgentContentPart, duration: number, stream = false) => {
    parts = forLocales((locale) => [...parts[locale], createPart(locale)])
    steps.push({ duration, parts, streamId: stream ? parts['zh-CN'].at(-1)?.id : undefined })
  }
  const finishTool = (title: (locale: Locale) => string) => {
    parts = forLocales((locale) => parts[locale].map((part, index) => index === parts[locale].length - 1
      ? { ...part, title: title(locale), content: messagePreviewCopy[locale].toolResult, metadata: { ...part.metadata, status: 'completed' } }
      : part))
  }
  if (mode === 'tool-group') {
    append((locale) => ({ id: `${prefix}-intro`, kind: 'markdown', content: messagePreviewCopy[locale].groupIntro }), 1000)
    for (let count = 1; count <= 5; count += 1) {
      append((locale) => ({ id: `${prefix}-tool-${count}`, kind: 'tool_call', title: messagePreviewCopy[locale].groupRunning.replace('{count}', String(count)), content: '', metadata: { status: 'running' } }), 1800)
      finishTool((locale) => messagePreviewCopy[locale].groupDone.replace('{count}', String(count)))
      steps.push({ duration: count === 3 || count === 4 ? 2200 : 700, parts })
    }
    return steps
  }
  if (mode === 'sequence' || mode === 'first-token') {
    steps.push({ duration: 1600, parts })
    append((locale) => ({ id: `${prefix}-reasoning`, kind: 'reasoning', content: messagePreviewCopy[locale].reasoning }), 1800, true)
    append((locale) => ({ id: `${prefix}-intro`, kind: 'markdown', content: messagePreviewCopy[locale].intro }), 1500, true)
  }
  if (mode === 'first-token') return steps
  if (mode !== 'answer') {
    append((locale) => ({ id: `${prefix}-read`, kind: 'tool_call', title: messagePreviewCopy[locale].readRunning, content: '', metadata: { tool_name: 'read_file', status: 'running' } }), 3200)
    finishTool((locale) => messagePreviewCopy[locale].readDone)
    steps.push({ duration: 900, parts })
    append((locale) => ({ id: `${prefix}-check`, kind: 'tool_call', title: messagePreviewCopy[locale].checkRunning, content: '', metadata: { status: 'running' } }), 3200)
    finishTool((locale) => messagePreviewCopy[locale].checkDone)
    steps.push({ duration: 800, parts })
  }
  if (mode !== 'tools') append((locale) => ({ id: `${prefix}-answer`, kind: 'markdown', content: messagePreviewCopy[locale].answer }), 2800, true)
  return steps
}

export function readPreviewFrame(steps: PreviewStep[], elapsed: number) {
  let remaining = elapsed
  for (const step of steps) {
    if (remaining < step.duration) return {
      done: false,
      parts: step.streamId ? forLocales((locale) => step.parts[locale].map((part) => part.id === step.streamId
        ? { ...part, content: part.content.slice(0, Math.max(1, Math.ceil(part.content.length * remaining / step.duration))) }
        : part)) : step.parts,
    }
    remaining -= step.duration
  }
  return { done: true, parts: steps.at(-1)?.parts ?? forLocales<AgentContentPart[]>(() => []) }
}
