import { useAgent } from './AgentContext'
import { AgentPanel } from './AgentPanel'
import type { AgentSidebarProps } from './AgentSidebar.types'

export type { AgentSidebarProps, AgentSidebarRenderContext, AgentSidebarSlot } from './AgentSidebar.types'

/** A ready-to-use panel driven by the nearest CornAgentProvider. */
export function AgentSidebar({ layout = 'overlay', ...props }: AgentSidebarProps) {
  const workspace = useAgent()
  return workspace.open ? (
    <AgentPanel {...props} workspace={workspace} layout={layout} />
  ) : null
}
