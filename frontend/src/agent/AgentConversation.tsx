import { localizeSystemMessage } from '../i18n/systemMessages'
import { GithubOutlined, XOutlined } from '@ant-design/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
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

export function AgentConversation({ workspace, userName, focusPrompt = false, onSessionChange }: { workspace: AgentWorkspace; userName?: string; focusPrompt?: boolean; onSessionChange?: (sessionId: string) => void }) {
  const { locale, t } = useI18n()
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

  const submit = async (content: string, fileIds: string[]) => {
    if ((!content && fileIds.length === 0) || active || workspace.busy) return
    try {
      const sessionId = await workspace.send(content, fileIds)
      onSessionChange?.(sessionId)
      setDraft('')
      fileDraft.clearAfterSubmit()
      return true
    } catch {
      return false
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
    placeholder={t(active ? 'agentWorking' : 'askAnything')}
    disabled={active || workspace.busy}
    fileAccept={workspace.fileInput?.accepts.map((item) => item.mimeType).join(',')}
    fileError={fileDraft.error}
    fileFailed={fileDraft.failed}
    fileInputEnabled={workspace.fileInput?.enabled}
    files={fileDraft.files}
    fileProcessing={fileDraft.processing}
    loading={active}
    onAddFiles={fileDraft.addFiles}
    textareaRows={2}
    onRemoveFile={fileDraft.removeFile}
    onRetryFile={fileDraft.retryFile}
  />

  return <section className={`agent-conversation${emptyConversation ? ' agent-conversation--empty' : ''}`} aria-label={t('conversation')}>
    {workspace.error && <div className="agent-error-banner" role="alert">{localizeSystemMessage(workspace.error, locale)}</div>}
    {workspace.available === false
      ? <div className="agent-empty-state"><h2>{t('unavailable')}</h2><p>{t('unavailableHelp')}</p></div>
      : emptyConversation
        ? <div className="agent-new-conversation">
          <div className="agent-new-conversation__title">
            <AgentThinkingOrb32 aria-hidden="true" className="agent-new-conversation__orb" state="composing" speed={0.6}/>
            <h1>{localizedGreeting(locale, userName)}</h1>
          </div>
          {prompt}
          <div className="agent-new-conversation__social-links">
            <a href="https://github.com/XiaoTongYuCode/CornAgent" target="_blank" rel="noopener noreferrer" aria-label="GitHub" title="GitHub">
              <GithubOutlined aria-hidden="true" />
            </a>
            <a href="https://x.com/tongyu_xiao" target="_blank" rel="noopener noreferrer" aria-label="X" title="X">
              <XOutlined aria-hidden="true" />
            </a>
          </div>
        </div>
        : <AgentMessageList workspace={workspace} />}
    {workspace.available !== false && !emptyConversation && pendingQuestion && <div className="agent-question-composer">
      <UserQuestionPart
        display="composer"
        onRespondUserQuestion={respond}
        part={{ ...pendingQuestion, kind: 'user_question', metadata: pendingQuestion.metadata ? { ...pendingQuestion.metadata } : null }}
      />
    </div>}
    {workspace.available !== false && !emptyConversation && !pendingQuestion && prompt}
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
