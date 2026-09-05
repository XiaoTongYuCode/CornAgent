import { useAgent } from './AgentContext'
import { AgentPanel } from './AgentPanel'

export interface AgentSidebarProps {
  layout?: 'overlay' | 'docked'
  userName?: string
}

/** A ready-to-use panel driven by the nearest CornAgentProvider. */
export function AgentSidebar({ layout = 'overlay', userName }: AgentSidebarProps) {
  const workspace = useAgent()
  return workspace.open ? (
    <AgentPanel workspace={workspace} userName={userName} layout={layout} />
  ) : null
}
