import { MessageCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { useI18n } from '../i18n'
import { useAgent } from './AgentContext'

export function AgentLauncher({
  children,
  className = '',
}: {
  children?: ReactNode
  className?: string
}) {
  const workspace = useAgent()
  const { t } = useI18n()
  return (
    <button
      type="button"
      className={`agent-launcher ${className}`}
      onClick={() => workspace.setOpen(true)}
    >
      <MessageCircle size={16} aria-hidden="true" />
      {children ?? t('openAgent')}
    </button>
  )
}
