import { useI18n } from '../../i18n'
import { localizeSystemMessage } from '../../i18n/systemMessages'
import { AnimatePresence } from 'motion/react'
import { AnimatedMessageBody } from './AnimatedMessageBody'
import Markdown from '@lobehub/ui/es/Markdown/index'
import { ScrollArea } from '@lobehub/ui/es/ScrollArea/index'
import { ChevronRight, type LucideIcon } from 'lucide-react'
import {
  createElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ComponentProps,
  type CSSProperties,
  type ReactNode,
  type UIEvent,
} from 'react'

import { getCollapsibleTitleIcon } from './collapsibleTitleIcon'
import { ShimmerText } from '../../components/ShimmerText'
import { TextSwap } from '../../components/TextSwap'

type MarkdownVariant = ComponentProps<typeof Markdown>['variant']
type MarkdownComponents = ComponentProps<typeof Markdown>['components']
const DEFAULT_SCROLL_AREA_STYLE: CSSProperties = {
  maxHeight: 192,
  width: '100%',
  background: 'transparent',
}
const SCROLL_AREA_CONTENT_PROPS: NonNullable<ComponentProps<typeof ScrollArea>['contentProps']> = {
  style: {
    padding: 0,
  },
}
const SCROLL_AREA_SCROLLBAR_PROPS: NonNullable<ComponentProps<typeof ScrollArea>['scrollbarProps']> = {
  style: {
    display: 'none',
  },
}

interface CollapsibleContentProps {
  title: ReactNode
  content?: string
  open: boolean
  onOpen: () => void
  onClose: () => void
  collapsible?: boolean
  variant?: MarkdownVariant
  components?: MarkdownComponents
  fontSize?: number
  scrollable?: boolean
  streaming?: boolean
  scrollAreaStyle?: CSSProperties
  autoScrollToBottom?: boolean
  children?: ReactNode
  className?: string
  bodyClassName?: string
  titleClassName?: string
  titleStreaming?: boolean
  titleTransition?: boolean
  titleIcon?: LucideIcon | null
  titleIconColor?: string | null
  enableEnterAnimation?: boolean
  hideChevron?: boolean
}

function getTitleText(title: ReactNode): string {
  if (typeof title === 'string') {
    return title
  }
  if (typeof title === 'number') {
    return String(title)
  }
  return ''
}

export function CollapsibleContent({
  title,
  content,
  open,
  onOpen,
  onClose,
  collapsible = true,
  variant = 'chat',
  components,
  fontSize = 12,
  scrollable = true,
  streaming = false,
  scrollAreaStyle = DEFAULT_SCROLL_AREA_STYLE,
  autoScrollToBottom = true,
  children,
  className,
  bodyClassName,
  titleClassName = '',
  titleStreaming = false,
  titleTransition = false,
  titleIcon,
  titleIconColor,
  enableEnterAnimation = false,
  hideChevron = false,
}: CollapsibleContentProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const isScrollPinnedToBottomRef = useRef(true)
  const {
    root: scrollAreaRootStyle,
    viewport: scrollAreaViewportStyle,
  } = useMemo(() => {
    const { maxHeight, height, ...root } = scrollAreaStyle
    return {
      root,
      viewport: {
        maxHeight,
        height,
        overflowY: 'auto',
      } satisfies CSSProperties,
    }
  }, [scrollAreaStyle])
  const hasCustomBody = children !== undefined && children !== null
  const hasContent = Boolean(content?.trim()) || hasCustomBody
  const isOpen = hasContent && (!collapsible || open)
  const titleText = getTitleText(title)
  const titleIconComponent = titleIcon === undefined ? getCollapsibleTitleIcon(titleText) : titleIcon
  const { locale } = useI18n()
  const displayTitle = typeof title === 'string' ? localizeSystemMessage(title, locale) : title
  const titleClasses = ['chat-collapsible-content__title-text', titleClassName].filter(Boolean).join(' ')

  const handleViewportScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget
    const distanceToBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
    isScrollPinnedToBottomRef.current = distanceToBottom <= 48
  }, [])

  const scrollAreaViewportProps = useMemo(() => ({
    ref: viewportRef,
    onScroll: handleViewportScroll,
    style: scrollAreaViewportStyle,
  }), [handleViewportScroll, scrollAreaViewportStyle])

  const renderedContent = useMemo(() => {
    if (hasCustomBody) {
      return children
    }

    return (
      <Markdown
        animated={streaming}
        components={components}
        enableStream={streaming}
        fontSize={fontSize}
        streamSmoothingPreset="realtime"
        variant={variant}
      >
        {content ?? ''}
      </Markdown>
    )
  }, [children, components, content, fontSize, hasCustomBody, streaming, variant])

  const renderedBody = useMemo(() => {
    if (!scrollable) {
      return renderedContent
    }

    return (
      <ScrollArea
        contentProps={SCROLL_AREA_CONTENT_PROPS}
        scrollFade
        scrollbarProps={SCROLL_AREA_SCROLLBAR_PROPS}
        style={scrollAreaRootStyle}
        viewportProps={scrollAreaViewportProps}
      >
        {renderedContent}
      </ScrollArea>
    )
  }, [renderedContent, scrollable, scrollAreaRootStyle, scrollAreaViewportProps])

  useEffect(() => {
    if (
      !scrollable ||
      !autoScrollToBottom ||
      !isOpen ||
      !isScrollPinnedToBottomRef.current
    ) {
      return
    }

    const viewport = viewportRef.current
    if (!viewport) {
      return
    }

    const animationFrame = window.requestAnimationFrame(() => {
      viewport.scrollTo({
        top: viewport.scrollHeight,
      })
      isScrollPinnedToBottomRef.current = true
    })

    return () => {
      window.cancelAnimationFrame(animationFrame)
    }
  }, [autoScrollToBottom, children, content, isOpen, scrollable])

  const handleToggle = () => {
    if (!hasContent || !collapsible) {
      return
    }

    if (isOpen) {
      onClose()
      return
    }

    onOpen()
  }

  return (
    <div
      className={[
        'chat-collapsible-content',
        enableEnterAnimation && 'chat-collapsible-content--enter',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <button
        aria-expanded={isOpen}
        className={[
          'chat-collapsible-content__toggle',
          (!hasContent || !collapsible) && 'chat-collapsible-content__toggle--disabled',
          !collapsible && 'chat-collapsible-content__toggle--static',
        ]
          .filter(Boolean)
          .join(' ')}
        disabled={!hasContent || !collapsible}
        onClick={handleToggle}
        type="button"
      >
        <span className="chat-collapsible-content__title">
          {titleIconComponent
            ? createElement(titleIconComponent, {
                'aria-hidden': true,
                className: 'chat-collapsible-content__title-icon',
                size: 14,
                style: titleIconColor ? { color: titleIconColor } : undefined,
              })
            : null}
          {titleTransition && typeof displayTitle === 'string'
            ? <TextSwap text={displayTitle} shimmer={titleStreaming} className={titleClasses} />
            : <ShimmerText active={titleStreaming} className={titleClasses}>{displayTitle}</ShimmerText>}
        </span>
        {hasContent && collapsible && !hideChevron ? (
          <ChevronRight
            className={[
              'chat-collapsible-content__chevron',
              isOpen && 'chat-collapsible-content__chevron--open',
            ]
              .filter(Boolean)
              .join(' ')}
            size={14}
          />
        ) : null}
      </button>
      <AnimatePresence initial={false}>
        {isOpen ? (
          <AnimatedMessageBody
            key="body"
            className={['chat-collapsible-content__body', 'chat-collapsible-content__body--open', bodyClassName].filter(Boolean).join(' ')}
            motionPreset="accordion"
          >
            <div className="chat-collapsible-content__body-inner">
              <div className="chat-collapsible-content__body-content">
                {renderedBody}
              </div>
            </div>
          </AnimatedMessageBody>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
