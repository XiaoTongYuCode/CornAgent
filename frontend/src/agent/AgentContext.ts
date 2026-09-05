import { createContext, useContext } from 'react'
import type { AgentWorkspace } from './useAgentWorkspace'

export const AgentContext = createContext<AgentWorkspace | null>(null)

/** Access the workspace shared by the chat page, launcher and sidebar. */
export function useAgent(): AgentWorkspace {
  const workspace = useContext(AgentContext)
  if (!workspace) throw new Error('useAgent must be used inside CornAgentProvider.')
  return workspace
}
