import { Check, ChevronRight, CircleAlert, FilePenLine, Minus, SearchCheck } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n/catalog'
import { OPERATION_STATES, operationEvidence, type AgentOperationState } from '../operationEvidence'
import type { AgentContentPart } from '../types'

const stateKeys: Record<AgentOperationState, MessageKey> = {
  committed: 'operationCommitted', partial: 'operationPartial', draft: 'operationDraft',
  noop: 'operationNoop', failed: 'operationFailed', unknown: 'operationUnknown',
}
const actionKeys = {
  create: 'operationCreated', update: 'operationUpdated', delete: 'operationDeleted', attach: 'operationAttached',
} as const
const stateIcons = {
  committed: Check, partial: CircleAlert, draft: FilePenLine, noop: Minus, failed: CircleAlert, unknown: SearchCheck,
}

/** The message page and embedded panel share this durable receipt projection. */
export function TurnChanges({ parts }: { parts: AgentContentPart[] }) {
  const { t } = useI18n()
  const operations = operationEvidence(parts)
  if (!operations.length) return null
  const counts = Object.fromEntries(OPERATION_STATES.map((state) => [
    state, operations.reduce((sum, operation) => sum + operation.counts[state], 0),
  ])) as Record<AgentOperationState, number>
  return <section className="agent-turn-changes" aria-label={t('operationEvidence')}>
    <details>
      <summary className="agent-turn-changes__summary">
        <span className="agent-turn-changes__heading"><SearchCheck size={15} aria-hidden />{t('operationEvidence')}</span>
        <span className="agent-turn-changes__totals">
          {OPERATION_STATES.filter((state) => counts[state] > 0).map((state) => <span key={state}
            className={`agent-turn-changes__count agent-turn-changes__count--${state}`}>
            {t(stateKeys[state])} {counts[state]}
          </span>)}
        </span>
        <ChevronRight className="agent-turn-changes__chevron" size={14} aria-hidden />
      </summary>
      <div className="agent-turn-changes__body">
        <p className="agent-turn-changes__notice">{t('operationEvidenceHelp')}</p>
        <ul className="agent-turn-changes__list">
          {operations.map((operation) => {
            const Icon = stateIcons[operation.state]
            return <li className="agent-turn-changes__operation" key={operation.id}>
              <div className="agent-turn-changes__operation-heading">
                <span><Icon size={14} aria-hidden />{operation.tool || t('operationUntitled')}</span>
                <span className={`agent-turn-changes__count agent-turn-changes__count--${operation.state}`}>{t(stateKeys[operation.state])}</span>
              </div>
              {operation.changes.length > 0 ? <ul className="agent-turn-changes__resources">
                {operation.changes.map((change, index) => <li key={`${change.resource_type}:${change.resource_id}:${index}`}>
                  <div className="agent-turn-changes__resource-heading">
                    <strong>{change.title || change.resource_type}</strong><span>{t(actionKeys[change.action])}</span>
                  </div>
                  {change.fields && change.fields.length > 0 ? <dl className="agent-turn-changes__fields">
                    {change.fields.map((field, fieldIndex) => <div key={fieldIndex}>
                      <dt>{field.label}</dt>
                      <dd>{field.before !== undefined ? <div className="agent-turn-changes__comparison">
                        <div><small>{t('operationBefore')}</small><span>{field.before || t('operationEmpty')}</span></div>
                        <div><small>{t('operationAfter')}</small><span>{field.value || t('operationEmpty')}</span></div>
                      </div> : <span>{field.value || t('operationEmpty')}</span>}</dd>
                    </div>)}
                  </dl> : <p className="agent-turn-changes__notice">{t('operationNoFieldDetails')}</p>}
                  {change.href ? <a className="agent-turn-changes__link" href={change.href}>{t('operationOpenRecord')}</a> : null}
                </li>)}
              </ul> : <p className="agent-turn-changes__notice">{t(operation.state === 'unknown' ? 'operationUnknownHelp'
                : operation.state === 'draft' ? 'operationDraftHelp' : 'operationNoResourceDetails')}</p>}
              {operation.truncated ? <p className="agent-turn-changes__notice">{t('operationMoreInReceipt')}</p> : null}
            </li>
          })}
        </ul>
      </div>
    </details>
  </section>
}
