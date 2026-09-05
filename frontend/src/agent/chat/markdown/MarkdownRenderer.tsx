import Markdown from '@lobehub/ui/es/Markdown/index'
import { useMemo, type ComponentProps } from 'react'

export type MarkdownVariant = ComponentProps<typeof Markdown>['variant']
export type MarkdownComponents = ComponentProps<typeof Markdown>['components']

export interface AgentMarkdownLinkPayload {
  href: string
}

export interface AgentMarkdownLinkHandlers {
  onLinkClick?: (payload: AgentMarkdownLinkPayload) => void
}

interface MarkdownRendererProps extends AgentMarkdownLinkHandlers {
  fontSize: number
  streaming?: boolean
  value: string
  variant: MarkdownVariant
}

export function MarkdownRenderer({ fontSize, onLinkClick, streaming = false, value, variant }: MarkdownRendererProps) {
  const components = useMemo<MarkdownComponents>(() => ({
    a: ({ href, ...props }) => <a
      {...props}
      href={href}
      onClick={(event) => {
        if (!href || !onLinkClick) return
        event.preventDefault()
        onLinkClick({ href })
      }}
      rel="noreferrer"
      target="_blank"
    />,
  }), [onLinkClick])

  return <Markdown
    animated={streaming}
    components={components}
    enableStream={streaming}
    fontSize={fontSize}
    streamSmoothingPreset="realtime"
    variant={variant}
  >{value}</Markdown>
}
