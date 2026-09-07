import { useRef, useState } from 'react'
import { apiErrorMessage } from '../../api/transport'
import { useI18n } from '../../i18n'
import { localizeSystemMessage } from '../../i18n/systemMessages'

/** Keep failed operations recoverable and prevent duplicate submissions. */
export function useMessageAction() {
  const { t, locale, text } = useI18n()
  const inFlight = useRef(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<{ reason: unknown } | null>(null)
  const execute = async (operation: () => Promise<void>) => {
    if (inFlight.current) return false
    inFlight.current = true
    setPending(true)
    setError(null)
    try {
      await operation()
      return true
    } catch (reason) {
      setError({ reason })
      return false
    } finally {
      inFlight.current = false
      setPending(false)
    }
  }
  return {
    execute, pending,
    error: error === null ? null : apiErrorMessage(error.reason,
      error.reason instanceof Error ? localizeSystemMessage(error.reason.message, locale) : t('messageActionFailed'), text),
    clearError: () => setError(null),
  }
}
