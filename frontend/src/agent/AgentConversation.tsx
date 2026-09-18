import { apiErrorMessage } from '../api/transport'
import { AgentInputQueue } from './AgentInputQueue'
import type { AgentInput } from './types'
import { ListEnd } from 'lucide-react'
import { localizeSystemMessage } from '../i18n/systemMessages'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createClientId } from '../client-id'
import { useI18n, type Locale } from '../i18n'
import { AgentThinkingOrb32 } from './AgentThinkingOrb32'
import { UserQuestionPart } from './chat/UserQuestionPart'
import { PromptPanel } from './chat/PromptPanel'
import { useAgentFileDraft } from './chat/useAgentFileDraft'
import type { AgentChatUserQuestionResponse } from './chat/types'
import { AgentMessageList } from './AgentMessageList'
import { activeLineage, questionMetadata } from './types'
import type { AgentWorkspace } from './useAgentWorkspace'

export function AgentConversation({ workspace, userName, focusPrompt = false, onSessionChange, emptyStateFooter }: { workspace: AgentWorkspace; emptyStateFooter?: ReactNode; userName?: string; focusPrompt?: boolean; onSessionChange?: (sessionId: string) => void }) {
  const { locale, t } = useI18n()
  const beforeEditDraft = useRef('')
  const submitInFlight = useRef(false)
  const [editingInput, setEditingInput] = useState<AgentInput | null>(null)
  const [sendingInput, setSendingInput] = useState(false)
  const [inputError, setInputError] = useState<string | null>(null)
  const currentRevision = useRef(workspace.draftRevisionKey)
  useEffect(() => { currentRevision.current = workspace.draftRevisionKey }, [workspace.draftRevisionKey])
  const currentEdit = editingInput?.session_id === workspace.session?.id ? editingInput : null
  const [draftState, setDraftState] = useState({ key: workspace.draftRevisionKey, value: '' })
  const draft = draftState.key === workspace.draftRevisionKey ? draftState.value : ''
  const setDraft = (value: string) => setDraftState({ key: workspace.draftRevisionKey, value })
  const fileDraft = useAgentFileDraft({
    capabilities: workspace.fileInput,
    revisionKey: workspace.draftRevisionKey,
    upload: workspace.uploadFile,
    remove: workspace.deleteFile,
  })
  const questionKeys = useRef(new Map<string, string>())
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const focusAfterRunRef = useRef<string | null>(null)
  const currentRun = workspace.snapshot?.run ?? workspace.session?.activeRun
  const active = Boolean(currentRun && !['completed', 'failed', 'cancelled'].includes(currentRun.status))
  const currentParts = useMemo(() => workspace.snapshot?.contentParts
    ?? workspace.session?.messages.find((message) => message.id === currentRun?.assistantMessageId)?.contentParts
    ?? [], [currentRun?.assistantMessageId, workspace.session?.messages, workspace.snapshot?.contentParts])
  const pendingQuestion = useMemo(() => [...currentParts]
    .reverse().find((part) => questionMetadata(part)?.status === 'pending'), [currentParts])
  const emptyConversation = workspace.available !== false && activeLineage(workspace.session).length === 0 && !active && !pendingQuestion
  const promptFocusable = workspace.available !== false && !active && !workspace.busy && !pendingQuestion

  useEffect(() => {
    if (active) focusAfterRunRef.current = workspace.draftRevisionKey
    else if (focusAfterRunRef.current !== workspace.draftRevisionKey) focusAfterRunRef.current = null
    if (!promptFocusable || (!focusPrompt && !focusAfterRunRef.current)) return
    const frame = window.requestAnimationFrame(() => {
      promptRef.current?.focus({ preventScroll: true })
      focusAfterRunRef.current = null
    })
    return () => window.cancelAnimationFrame(frame)
  }, [active, focusPrompt, promptFocusable, workspace.draftRevisionKey])

  const submit = async (content: string, fileIds: string[], mode: 'queue' | 'steer' = 'queue') => {
    if ((!content && fileIds.length === 0 && !currentEdit?.file_ids.length) || workspace.busy || submitInFlight.current) return false
    submitInFlight.current = true
    const revision = workspace.draftRevisionKey
    setSendingInput(true)
    setInputError(null)
    try {
      if (currentEdit) {
        await workspace.changeInput(currentEdit, { content })
        setEditingInput(null)
      } else if (active) {
        await workspace.queueInput(content, fileIds, mode)
      } else {
        const sessionId = await workspace.send(content, fileIds)
        onSessionChange?.(sessionId)
      }
      if (revision === currentRevision.current) {
        setDraft(currentEdit ? beforeEditDraft.current : '')
        if (!currentEdit) fileDraft.clearAfterSubmit()
      }
      return true
    } catch (reason) {
      setInputError(apiErrorMessage(reason, t('inputFailed')))
      return false
    } finally {
      submitInFlight.current = false
      setSendingInput(false)
    }
  }
  const respond = async (response: AgentChatUserQuestionResponse) => {
    const key = questionKeys.current.get(response.questionId) ?? createClientId()
    questionKeys.current.set(response.questionId, key)
    if (response.action === 'cancel') {
      await workspace.respond(response.questionId, { action: 'cancel' }, key)
    } else if (response.optionId) {
      await workspace.respond(response.questionId, { action: 'answer', option_id: response.optionId }, key)
    } else {
      await workspace.respond(response.questionId, { action: 'answer', content: response.content?.trim() ?? '' }, key)
    }
    questionKeys.current.delete(response.questionId)
  }

  const prompt = <PromptPanel
    autoFocus={focusPrompt && promptFocusable}
    className="agent-conversation-prompt"
    ref={promptRef}
    value={draft}
    onChange={setDraft}
    onStartResearch={({ prompt: nextPrompt, fileIds }) => submit(nextPrompt, fileIds)}
    onStop={workspace.cancel}
    stopWhenEmpty={active && !currentEdit}
    onAlternateSubmit={active ? ({ prompt, fileIds }) => submit(prompt, fileIds, 'steer') : undefined}
    submitIcon={active ? <ListEnd size={16} /> : undefined}
    submitTooltip={active ? t('queueHint') : undefined}
    maxLength={40000}
    placeholder={t(active ? 'queuePlaceholder' : 'askAnything')}
    disabled={workspace.busy || sendingInput}
    fileAccept={workspace.fileInput?.accepts.map((item) => item.mimeType).join(',')}
    fileError={fileDraft.error}
    fileFailed={!currentEdit && fileDraft.failed}
    fileInputEnabled={workspace.fileInput?.enabled && !currentEdit}
    files={currentEdit ? [] : fileDraft.files}
    hasExistingFiles={Boolean(currentEdit?.file_ids.length)}
    fileProcessing={!currentEdit && fileDraft.processing}
    loading={false}
    onAddFiles={fileDraft.addFiles}
    textareaRows={2}
    onRemoveFile={fileDraft.removeFile}
    onRetryFile={fileDraft.retryFile}
  />

  return <section className={`agent-conversation${emptyConversation ? ' agent-conversation--empty' : ''}`} aria-label={t('conversation')}>
    {(inputError || workspace.error) && <div className="agent-error-banner" role="alert">{localizeSystemMessage(inputError || workspace.error || '', locale)}</div>}
    {workspace.available === false
      ? <div className="agent-empty-state"><h2>{t('unavailable')}</h2><p>{t(workspace.unavailableReason === 'model_not_configured' ? 'modelNotConfigured' : workspace.unavailableReason === 'event_stream_not_configured' ? 'eventStreamNotConfigured' : 'unavailableHelp')}</p></div>
      : emptyConversation
        ? <div className="agent-new-conversation">
          <div className="agent-new-conversation__title">
            <AgentThinkingOrb32 aria-hidden="true" className="agent-new-conversation__orb" state="composing" speed={0.6}/>
            <h1>{localizedGreeting(locale, userName)}</h1>
          </div>
          {prompt}
          {emptyStateFooter}
        </div>
        : <AgentMessageList workspace={workspace} />}
    {workspace.available !== false && !emptyConversation && <div className="agent-conversation-input">
    {pendingQuestion && <div className="agent-question-composer">
      <UserQuestionPart
        display="composer"
        onRespondUserQuestion={respond}
        part={{ ...pendingQuestion, kind: 'user_question', metadata: pendingQuestion.metadata ? { ...pendingQuestion.metadata } : null }}
      />
    </div>}
      <AgentInputQueue workspace={workspace} disabled={sendingInput || Boolean(currentEdit)} onEdit={async input => {
        beforeEditDraft.current = draft
        setEditingInput(input)
        setDraft(input.content)
        promptRef.current?.focus()
      }} />
      {currentEdit && <div className="agent-input-editing">{t('editingQueuedMessage')}
        <button onClick={() => { setEditingInput(null); setDraft(beforeEditDraft.current) }}>{t('cancel')}</button>
      </div>}
      {prompt}
    </div>}
  </section>
}

function localizedGreeting(locale: Locale, userName?: string): string {
  const hour = new Date().getHours()
  const greeting = locale === 'zh-CN'
    ? hour >= 6 && hour < 12
      ? '早上好'
      : hour >= 12 && hour < 18
        ? '下午好'
        : '晚上好'
    : hour >= 6 && hour < 12
      ? 'Good morning'
      : hour >= 12 && hour < 18
        ? 'Good afternoon'
        : 'Good evening'
  const name = userName?.trim()
  if (locale === 'zh-CN') return name ? `${greeting}，${name}` : greeting
  return name ? `${greeting}, ${name}` : greeting
}
