import { useI18n } from '../../i18n'
import { apiErrorMessage } from '../../api/transport'
import { localizeSystemMessage } from '../../i18n/systemMessages'
import { CheckCircle2, CornerDownLeft, MessageCircleQuestion, ShieldCheck, Pencil, X, type LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Input, Tooltip, Typography } from 'antd'

import { CollapsibleContent } from './CollapsibleContent'
import {
  getMetadataString,
  getUserQuestionOptions,
  getUserQuestionStatus,
  type UserQuestionOption,
} from './userQuestion'
import type {
  AgentChatMessageContentPart,
  AgentChatUserQuestionResponse,
} from './types'

interface UserQuestionPartProps {
  display?: 'composer' | 'message'
  onRespondUserQuestion?: (response: AgentChatUserQuestionResponse) => Promise<void> | void
  open?: boolean
  part: AgentChatMessageContentPart
}

const noop = () => {}

function UserQuestionTitle({
  className,
  icon,
  title,
}: {
  className: string
  icon?: LucideIcon | null
  title: string
}) {
  return (
    <CollapsibleContent
      className={className}
      collapsible={false}
      content=""
      fontSize={12}
      onClose={noop}
      onOpen={noop}
      open={false}
      scrollable={false}
      title={title}
      titleTransition
      titleIcon={icon}
      variant="chat"
    />
  )
}

export function UserQuestionPart({
  display = 'message',
  onRespondUserQuestion,
  open = true,
  part,
}: UserQuestionPartProps) {
  const { t, locale, text } = useI18n()
  const metadata = part.metadata
  const questionId = getMetadataString(metadata, 'question_id')
  const isApproval = getMetadataString(metadata, 'interaction') === 'tool_approval'
  const status = getUserQuestionStatus(part)
  const answerContent = getMetadataString(metadata, 'answer_content')
  const selectedOptionId = getMetadataString(metadata, 'selected_option_id')
  const options = getUserQuestionOptions(metadata)
  const [customContent, setCustomContent] = useState('')
  const [draftSelectedOptionId, setDraftSelectedOptionId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<{ reason: unknown } | null>(null)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const isSubmittingRef = useRef(false)
  const isPending = status === 'pending'
  const isComposerOpen = display !== 'composer' || open
  const isDisabled = !isComposerOpen || !isPending || !questionId || !onRespondUserQuestion || isSubmitting
  const customAnswer = customContent.trim()
  const effectiveSelectedOptionId = draftSelectedOptionId ?? (isApproval ? null : options[0]?.id) ?? null
  const selectedOption = options.find((option) => option.id === effectiveSelectedOptionId) ?? null

  const moveSelectedOption = useCallback((direction: -1 | 1) => {
    if (isDisabled || options.length === 0) {
      return
    }
    const currentIndex = Math.max(
      0,
      options.findIndex((option) => option.id === effectiveSelectedOptionId),
    )
    const nextIndex = (currentIndex + direction + options.length) % options.length
    setDraftSelectedOptionId(options[nextIndex]?.id ?? null)
  }, [effectiveSelectedOptionId, isDisabled, options, setDraftSelectedOptionId])

  const handleOptionKeyboardNavigation = useCallback((event: KeyboardEvent) => {
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      event.stopPropagation()
      moveSelectedOption(-1)
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      event.stopPropagation()
      moveSelectedOption(1)
    }
  }, [moveSelectedOption])

  const respond = useCallback(async (response: AgentChatUserQuestionResponse) => {
    if (!onRespondUserQuestion || isSubmittingRef.current) {
      return
    }
    isSubmittingRef.current = true
    setIsSubmitting(true)
    setSubmitError(null)
    try {
      await onRespondUserQuestion(response)
      setCustomContent('')
    } catch (error) {
      setSubmitError({ reason: error })
    } finally {
      isSubmittingRef.current = false
      setIsSubmitting(false)
    }
  }, [onRespondUserQuestion, setCustomContent, setIsSubmitting, setSubmitError])

  const submitOption = useCallback((option: UserQuestionOption) => {
    if (!questionId || isDisabled) {
      return
    }
    setDraftSelectedOptionId(option.id)
    setCustomContent('')
    void respond({
      action: 'answer',
      content: option.content,
      optionId: option.id,
      questionId,
    })
  }, [isDisabled, questionId, respond, setCustomContent, setDraftSelectedOptionId])

  const submitAnswer = useCallback(() => {
    if (!questionId) {
      return
    }
    if (customAnswer) {
      void respond({
        action: 'answer',
        content: customAnswer,
        optionId: null,
        questionId,
      })
      return
    }
    if (!selectedOption) {
      return
    }
    void respond({
      action: 'answer',
      content: selectedOption.content,
      optionId: selectedOption.id,
      questionId,
    })
  }, [customAnswer, questionId, respond, selectedOption])

  const cancelQuestion = useCallback(() => {
    if (!questionId) {
      return
    }
    void respond({
      action: 'cancel',
      questionId,
    })
  }, [questionId, respond])

  useEffect(() => {
    if (isApproval || !isPending || display !== 'composer' || !open) {
      return
    }

    const handleDocumentKeyDown = (event: KeyboardEvent) => {
      const root = rootRef.current
      const target = event.target
      if (!root || !(target instanceof Node)) {
        return
      }
      const isFromUserQuestion = root.contains(target)
      const isFromDocumentBody = (
        target === document.body ||
        target === document.documentElement ||
        document.activeElement === document.body ||
        document.activeElement === document.documentElement
      )
      if (!isFromUserQuestion && !isFromDocumentBody) {
        return
      }

      const isTextEntryTarget = target instanceof HTMLElement && (
        target.isContentEditable ||
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT'
      )
      if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
        if (isTextEntryTarget) {
          return
        }
        handleOptionKeyboardNavigation(event)
        return
      }
      if (event.key === 'Escape' && !isDisabled) {
        event.preventDefault()
        event.stopPropagation()
        cancelQuestion()
        return
      }
      if (event.key === 'Enter' && !event.shiftKey && isFromDocumentBody) {
        event.preventDefault()
        event.stopPropagation()
        submitAnswer()
      }
    }

    document.addEventListener('keydown', handleDocumentKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleDocumentKeyDown, true)
    }
  }, [cancelQuestion, display, handleOptionKeyboardNavigation, isApproval, isDisabled, isPending, open, submitAnswer])

  if (!isPending) {
    const isAnswered = status === 'answered'
    const resultTitle = isApproval
      ? t(isAnswered && selectedOptionId === 'option-1' ? 'operationApproved' : 'operationCancelled')
      : isAnswered
      ? t(selectedOptionId ? 'questionOptionAnswered' : 'questionAnswered', { answer: answerContent || t('answerSubmitted') })
      : t('questionSkipped')

    return (
      <UserQuestionTitle
        className="chat-markdown-message-content__tool chat-markdown-message-content__user-question-result"
        icon={isAnswered && (!isApproval || selectedOptionId === 'option-1') ? CheckCircle2 : X}
        title={resultTitle}
      />
    )
  }

  if (display === 'message') {
    return (
      <UserQuestionTitle
        className="chat-markdown-message-content__tool chat-markdown-message-content__user-question-tool"
        title={t(isApproval ? 'waitingApproval' : 'askingQuestion')}
        icon={isApproval ? ShieldCheck : MessageCircleQuestion}
      />
    )
  }

  return (
    <div
      className={[
        'chat-markdown-message-content__user-question',
        display === 'composer' && 'chat-markdown-message-content__user-question--composer',
        display === 'composer' && 't-panel-slide',
      ].filter(Boolean).join(' ')}
      data-open={display === 'composer' ? String(open) : undefined}
      ref={rootRef}
    >
      <div className="chat-markdown-message-content__user-question-header">
        <Typography.Text className="chat-markdown-message-content__user-question-title">
          {part.content}
        </Typography.Text>
      </div>
      <div className="chat-markdown-message-content__user-question-options">
        {options.map((option, index) => (
          <Tooltip key={option.id} trigger={['hover', 'focus']} title={<span className="agent-option-tooltip">{option.content}{option.description && <><br />{option.description}</>}</span>}>
          <Button
            aria-label={isApproval ? option.content : undefined}
            aria-pressed={isApproval ? undefined : option.id === effectiveSelectedOptionId}
            block
            className={[
              'chat-markdown-message-content__user-question-option',
              option.id === effectiveSelectedOptionId &&
                'chat-markdown-message-content__user-question-option--selected',
            ].filter(Boolean).join(' ')}
            disabled={isDisabled}
            loading={isSubmitting && draftSelectedOptionId === option.id}
            onClick={() => {
              submitOption(option)
            }}
          >
            <span className="chat-markdown-message-content__user-question-option-inner">
              <span className="chat-markdown-message-content__user-question-option-index">
                {index + 1}
              </span>
              <span className="chat-markdown-message-content__user-question-option-content">
                {option.content}
              </span>
              {option.description ? (
                <span className="chat-markdown-message-content__user-question-option-description">
                  {option.description}
                </span>
              ) : null}
            </span>
          </Button>
          </Tooltip>
        ))}
      </div>
      {!isApproval && <div className="chat-markdown-message-content__user-question-custom">
        <span className="chat-markdown-message-content__user-question-custom-icon">
          <Pencil size={15} />
        </span>
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 5 }}
          className="chat-markdown-message-content__user-question-input"
          disabled={isDisabled}
          onChange={(event) => {
            setCustomContent(event.target.value)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && !isDisabled) {
              event.preventDefault()
              event.stopPropagation()
              cancelQuestion()
            }
          }}
          onPressEnter={(event) => {
            if (event.shiftKey) {
              return
            }
            event.preventDefault()
            submitAnswer()
          }}
          placeholder={t('customAnswer')}
          value={customContent}
        />
        <div className="chat-markdown-message-content__user-question-actions">
          <Button
            disabled={isDisabled}
            onClick={cancelQuestion}
            type="text"
          >
            {t('ignore')} <kbd>ESC</kbd>
          </Button>
          <Button
            className="chat-markdown-message-content__user-question-submit"
            disabled={isDisabled || (!customContent.trim() && !selectedOption)}
            onClick={submitAnswer}
            type="primary"
          >
            {t('submit')}
            <CornerDownLeft size={14} />
          </Button>
        </div>
      </div>}
      {submitError ? (
        <Typography.Text className="chat-markdown-message-content__user-question-error" role="alert">
          {apiErrorMessage(submitError.reason, submitError.reason instanceof Error
            ? localizeSystemMessage(submitError.reason.message, locale) : t('submitFailed'), text)}
        </Typography.Text>
      ) : null}
    </div>
  )
}
