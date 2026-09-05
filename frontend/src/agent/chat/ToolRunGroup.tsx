import { useI18n } from '../../i18n'
import { localizeSystemMessage } from '../../i18n/systemMessages'
import { ChevronRight, type LucideIcon } from 'lucide-react'
import { createElement, useState, type ReactNode } from 'react'

import type { MessageRenderGroupItem } from './utils/messageRenderPlan'
import { ShimmerText } from '../../components/ShimmerText'
import { TextSwap } from '../../components/TextSwap'

interface ToolRunGroupProps {
  children: ReactNode
  className?: string
  presentation: MessageRenderGroupItem['presentation']
  title: ReactNode
  titleStreaming?: boolean
  titleIcon?: LucideIcon | null
}

export function ToolRunGroup({
  children,
  className,
  presentation,
  title,
  titleStreaming = false,
  titleIcon,
}: ToolRunGroupProps) {
  const { locale } = useI18n()
  const [open, setOpen] = useState(false)
  const isGrouped = presentation === 'grouped'
  const isExpanded = !isGrouped || open
  const displayTitle = typeof title === 'string' ? localizeSystemMessage(title, locale) : title

  return (
    <div
      className={[
        'chat-tool-run-group',
        `chat-tool-run-group--${presentation}`,
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <button
        aria-expanded={isGrouped ? isExpanded : undefined}
        aria-hidden={!isGrouped}
        className="chat-collapsible-content__toggle chat-tool-run-group__toggle"
        disabled={!isGrouped}
        onClick={() => {
          if (isGrouped) {
            setOpen((current) => !current)
          }
        }}
        tabIndex={isGrouped ? 0 : -1}
        type="button"
      >
        <span className="chat-collapsible-content__title">
          {titleIcon
            ? createElement(titleIcon, {
                'aria-hidden': true,
                className: 'chat-collapsible-content__title-icon',
                size: 14,
              })
            : null}
          {typeof displayTitle === 'string'
            ? <TextSwap text={displayTitle} shimmer={titleStreaming} className="chat-collapsible-content__title-text" />
            : <ShimmerText active={titleStreaming} className="chat-collapsible-content__title-text">{displayTitle}</ShimmerText>}
        </span>
        <ChevronRight
          aria-hidden
          className={[
            'chat-collapsible-content__chevron',
            isExpanded && 'chat-collapsible-content__chevron--open',
          ]
            .filter(Boolean)
            .join(' ')}
          size={14}
        />
      </button>
      <div
        aria-hidden={!isExpanded}
        className={[
          'chat-tool-run-group__body',
          isExpanded && 'chat-tool-run-group__body--expanded',
        ]
          .filter(Boolean)
          .join(' ')}
        inert={!isExpanded}
      >
        <div className="chat-tool-run-group__body-inner">
          <div className="chat-tool-run-group__body-content">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
