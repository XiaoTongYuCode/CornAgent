import { Button, Input } from 'antd'
import { Pencil } from 'lucide-react'
import { useState } from 'react'
import { useI18n } from '../../i18n'
import type { AgentMessage } from '../types'
import type { AgentWorkspace } from '../useAgentWorkspace'
import { AgentMessageAttachments } from './AgentMessageAttachments'
import { MarkdownMessageContent } from './MarkdownMessageContent'
import { CopyMessageButton, MessageActionButton, MessageVersionControls } from './MessageActions'
import { useMessageAction } from './useMessageAction'

export function UserMessage({ message, disabled, workspace }: {
  message: AgentMessage
  disabled: boolean
  workspace: Pick<AgentWorkspace, 'edit' | 'switchVersion'>
}) {
  const { t } = useI18n()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.markdown)
  const action = useMessageAction()
  const unavailable = disabled || action.pending
  const cancel = () => { setEditing(false); action.clearError() }
  const submit = async () => {
    if (unavailable || (!draft.trim() && message.attachments.length === 0) || draft === message.markdown) return
    if (await action.execute(() => workspace.edit(message.id, draft))) setEditing(false)
  }

  return <section className="chat-message-list__turn chat-message-list__turn--user" data-message-turn-id={message.id}>
    {editing ? <form className="chat-message-list__user-editor" onSubmit={(event) => { event.preventDefault(); void submit() }}>
      <AgentMessageAttachments attachments={message.attachments} />
      <Input.TextArea
        aria-label={t('editedMessage')}
        autoFocus
        rows={3}
        className="chat-message-list__user-editor-input"
        variant="borderless"
        disabled={unavailable}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing) {
            if (event.key === 'Enter') event.preventDefault()
            return
          }
          if (event.key === 'Escape' && !action.pending) { event.preventDefault(); cancel() }
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submit() }
        }}
        value={draft}
      />
      <div className="chat-message-list__edit-buttons">
        <Button disabled={action.pending} onClick={cancel}>{t('cancel')}</Button>
        <Button type="primary" htmlType="submit" loading={action.pending} disabled={unavailable || (!draft.trim() && message.attachments.length === 0) || draft === message.markdown}>{t('saveAndSend')}</Button>
      </div>
    </form> : <>
      <div className="chat-message-list__user-title-row">
        <AgentMessageAttachments attachments={message.attachments} />
        <MarkdownMessageContent className="chat-message-list__user-title" content={message.markdown} display="title" fontSize={14} variant="chat" />
      </div>
      <div className="chat-message-list__user-footer">
        <div className="chat-message-list__message-actions chat-message-list__message-actions--user">
          <CopyMessageButton content={message.markdown} />
          <MessageActionButton label={t('editMessage')} disabled={unavailable} onClick={() => { setDraft(message.markdown); action.clearError(); setEditing(true) }}>
            <Pencil aria-hidden="true" size={12} />
          </MessageActionButton>
        </div>
        <div className="chat-message-list__message-actions">
          <MessageVersionControls message={message} disabled={unavailable} onSwitch={(id) => void action.execute(() => workspace.switchVersion(id))} />
        </div>
      </div>
    </>}
    {action.error && <p className="chat-message-list__action-error" role="alert">{action.error}</p>}
  </section>
}
