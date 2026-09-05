import { useMemo, type ReactNode } from 'react'
import { HttpAgentTransport } from '../api/client'
import type { CornAgentApiTransport } from '../api/transport'
import { AppProviders } from '../app/AppProviders'
import { I18nProvider } from '../i18n'
import { AgentContext } from './AgentContext'
import { HttpAgentGateway } from './gateway'
import { useAgentWorkspace } from './useAgentWorkspace'

export interface CornAgentProviderProps {
  children: ReactNode
  apiBaseUrl?: string
  principalKey?: string
  /** null starts a blank conversation; undefined lets the workspace select its latest session. */
  sessionId?: string | null
  transport?: CornAgentApiTransport
}

export function CornAgentProvider({ children, ...options }: CornAgentProviderProps) {
  return (
    <I18nProvider>
      <AppProviders>
        <WorkspaceProvider {...options}>{children}</WorkspaceProvider>
      </AppProviders>
    </I18nProvider>
  )
}

function WorkspaceProvider({
  children,
  apiBaseUrl = '/api/v1',
  principalKey = 'cornagent-local',
  sessionId,
  transport,
}: CornAgentProviderProps) {
  const gateway = useMemo(
    () => new HttpAgentGateway(transport ?? new HttpAgentTransport(apiBaseUrl)),
    [apiBaseUrl, transport],
  )
  const workspace = useAgentWorkspace(gateway, principalKey, sessionId)
  return <AgentContext.Provider value={workspace}>{children}</AgentContext.Provider>
}
