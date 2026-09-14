import type { CSSProperties, ReactNode } from 'react'
import type { AgentWorkspace } from './useAgentWorkspace'

export type AgentSidebarSlot = 'header' | 'body' | 'footer'

export interface AgentSidebarRenderContext {
  workspace: AgentWorkspace
  /** Close with the sidebar's exit transition. */
  close: () => void
  /** Whether starting or switching conversations is currently disabled. */
  busy: boolean
  actions: { newChat: ReactNode; history: ReactNode; close: ReactNode }
  /** The built-in content for the header or actions being customized. */
  defaultContent: ReactNode
}

export interface AgentSidebarProps {
  layout?: 'overlay' | 'docked'
  userName?: string
  title?: ReactNode
  icon?: ReactNode
  /** Recommended when title is a React element rather than plain text. */
  ariaLabel?: string
  renderHeader?: (context: AgentSidebarRenderContext) => ReactNode
  renderActions?: (context: AgentSidebarRenderContext) => ReactNode
  footer?: ReactNode
  emptyStateFooter?: ReactNode
  className?: string
  style?: CSSProperties
  classNames?: Partial<Record<AgentSidebarSlot, string>>
  styles?: Partial<Record<AgentSidebarSlot, CSSProperties>>
  /** Controlled width in CSS pixels. Use with onWidthChange. */
  width?: number
  defaultWidth?: number
  minWidth?: number
  maxWidth?: number
  resizable?: boolean
  onWidthChange?: (width: number) => void
  /** Uncontrolled width preference; null disables local persistence. */
  widthStorageKey?: string | null
}
