import { Check, ChevronLeft, ChevronRight, Copy, RefreshCcw } from 'lucide-react'
import { useEffect, useRef, useState, type ButtonHTMLAttributes } from 'react'
import { useI18n } from '../../i18n'
import type { AgentMessage } from '../types'
import { useMessageAction } from './useMessageAction'

export function MessageActionButton({ label, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button {...props} aria-label={label} className="chat-message-list__message-action" title={label} type="button" />
}

export function CopyMessageButton({ content }: { content: string }) {
  const { t } = useI18n()
  const [status, setStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (timer.current !== null) clearTimeout(timer.current) }, [])

  const copy = async () => {
    if (timer.current !== null) clearTimeout(timer.current)
    try {
      await navigator.clipboard.writeText(content)
      setStatus('copied')
    } catch {
      setStatus('failed')
    }
    timer.current = setTimeout(() => setStatus('idle'), 1600)
  }
  const label = t(status === 'copied' ? 'copied' : status === 'failed' ? 'copyFailed' : 'copy')
  return <MessageActionButton label={label} onClick={() => void copy()}>
    {status === 'copied' ? <Check aria-hidden="true" size={12} /> : <Copy aria-hidden="true" size={12} />}
  </MessageActionButton>
}

export function MessageVersionControls({ message, disabled, onSwitch }: {
  message: AgentMessage
  disabled?: boolean
  onSwitch(messageId: string): void
}) {
  const { t } = useI18n()
  if (message.versionCount <= 1) return null
  return <>
    <MessageActionButton label={t('previousVersion')} disabled={disabled || !message.previousVersionId} onClick={() => message.previousVersionId && onSwitch(message.previousVersionId)}>
      <ChevronLeft aria-hidden="true" size={12} />
    </MessageActionButton>
    <span className="chat-message-list__version-index">{message.versionIndex}/{message.versionCount}</span>
    <MessageActionButton label={t('nextVersion')} disabled={disabled || !message.nextVersionId} onClick={() => message.nextVersionId && onSwitch(message.nextVersionId)}>
      <ChevronRight aria-hidden="true" size={12} />
    </MessageActionButton>
  </>
}

export function AssistantMessageActions({ copyContent, message, disabled, onRegenerate, onSwitch }: {
  copyContent: string
  message: AgentMessage
  disabled: boolean
  onRegenerate(): Promise<void>
  onSwitch(messageId: string): Promise<void>
}) {
  const { t } = useI18n()
  const action = useMessageAction()
  return <>
    <div className="chat-message-list__message-actions chat-message-list__message-actions--assistant">
      <MessageActionButton label={t('regenerate')} disabled={disabled || action.pending} onClick={() => void action.execute(onRegenerate)}>
        <RefreshCcw aria-hidden="true" size={12} />
      </MessageActionButton>
      <MessageVersionControls message={message} disabled={disabled || action.pending} onSwitch={(id) => void action.execute(() => onSwitch(id))} />
      <CopyMessageButton content={copyContent} />
    </div>
    {action.error && <p className="chat-message-list__action-error" role="alert">{action.error}</p>}
  </>
}
