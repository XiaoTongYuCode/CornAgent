import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider, useI18n } from '../../i18n'
import { operationEvidence, operationHref } from '../operationEvidence'
import type { AgentContentPart } from '../types'
import { TurnChanges } from './TurnChanges'

const committed: AgentContentPart = {
  id: 'write-1', kind: 'tool_call', content: 'Saved', metadata: {
    tool_name: 'save_record', operation_outcome: { state: 'committed', counts: { committed: 1 } },
    changes: [{ resource_id: '1', resource_type: 'record', title: 'Original title', action: 'update',
      href: '/records/1', fields: [{ label: 'Original label', before: 'Original before', value: 'Original value' }] }],
  },
}
const unknown: AgentContentPart = {
  id: 'write-2', kind: 'tool_call', content: 'ok:true', metadata: {
    tool_name: 'legacy_tool', operation_outcome: { state: 'unknown', counts: { unknown: 1 } },
  },
}
function Harness() {
  const { toggleLocale } = useI18n()
  return <><button onClick={toggleLocale}>language</button><TurnChanges parts={[committed, unknown]} /></>
}

it('keeps expansion across language changes without translating business values', async () => {
  const user = userEvent.setup()
  const view = render(<I18nProvider><Harness /></I18nProvider>)
  expect(screen.getByRole('region', { name: '本轮操作回执' })).toBeVisible()
  expect(screen.getByText('已提交 1')).toBeVisible()
  expect(screen.getByText('未确认 1')).toBeVisible()
  await user.click(screen.getByText('本轮操作回执'))
  expect(view.container.querySelector('details')).toHaveAttribute('open')
  expect(screen.getByText('Original title')).toBeVisible()
  expect(screen.getByText('Original before')).toBeVisible()
  expect(screen.getByRole('link', { name: '打开记录' })).toHaveAttribute('href', '/records/1')
  await user.click(screen.getByRole('button', { name: 'language' }))
  expect(screen.getByRole('region', { name: 'Operation receipts' })).toBeVisible()
  expect(view.container.querySelector('details')).toHaveAttribute('open')
  expect(screen.getByText('Original label')).toBeVisible()
  expect(screen.getByText('Original value')).toBeVisible()
  expect(screen.getByText('Before')).toBeVisible()
  expect(screen.getByText(/No confirmed write evidence/)).toBeVisible()
})

it('keeps confirmed children visible when their batch partially failed', async () => {
  const user = userEvent.setup()
  render(<TurnChanges parts={[{ ...committed, metadata: {
    ...committed.metadata, operation_outcome: { state: 'partial', counts: { committed: 1, failed: 1 } },
  } }]} />)
  expect(screen.getByText('已提交 1')).toBeVisible()
  expect(screen.getByText('失败 1')).toBeVisible()
  await user.click(screen.getByText('本轮操作回执'))
  expect(screen.getByText('部分完成')).toBeVisible()
  expect(screen.getByText('Original title')).toBeVisible()
})

it('replaces the persisted receipt without double-counting after a snapshot', () => {
  const draft: AgentContentPart = { ...committed, metadata: {
    tool_name: 'save_record', operation_outcome: { state: 'draft', counts: { draft: 1 } },
  } }
  const evidence = operationEvidence([draft, committed])
  expect(evidence).toHaveLength(1)
  expect(evidence[0].state).toBe('committed')
  expect(evidence[0].counts.draft).toBe(0)
  expect(evidence[0].counts.committed).toBe(1)
})

it('does not derive evidence from model prose or raw tool acknowledgement', () => {
  const { container } = render(<TurnChanges parts={[
    { id: 'markdown', kind: 'markdown', content: 'Everything was saved!' },
    { id: 'tool', kind: 'tool_call', content: 'Saved!', metadata: { result: { ok: true, state: 'committed' } } },
  ]} />)
  expect(container).toBeEmptyDOMElement()
})

it('does not show deleted-resource links or unconfirmed changes', () => {
  const deleted: AgentContentPart = { ...committed, metadata: {
    ...committed.metadata, changes: [{ resource_id: '1', resource_type: 'record', title: 'Deleted', action: 'delete', href: '/records/1' }],
  } }
  const unconfirmed: AgentContentPart = { ...unknown, metadata: { ...unknown.metadata,
    changes: [{ resource_id: '2', resource_type: 'record', title: 'Unconfirmed change', action: 'update' }],
  } }
  expect(operationEvidence([deleted])[0].changes[0].href).toBeUndefined()
  expect(operationEvidence([unconfirmed])[0].changes).toHaveLength(0)
})

it.each(['javascript:alert(1)', 'https://other.example', '//other.example', '/%5cevil', '/%2fevil', '/\nunsafe', '/%zz'])('rejects unsafe operation link %s', (href) => {
  expect(operationHref(href)).toBeUndefined()
})

it('ignores malformed persisted metadata and sanitizes unknown fields', () => {
  expect(operationEvidence([{ ...committed, metadata: { operation_outcome: { state: 'made-up' } } }])).toEqual([])
  const malformed: AgentContentPart = { ...committed, metadata: {
    operation_outcome: { state: 'committed', counts: { committed: -1, failed: true, unknown: '1' } },
    changes: [null, { resource_id: '1', resource_type: 'record', action: 'update', fields: [null] }],
  } }
  const [evidence] = operationEvidence([malformed])
  expect(Object.values(evidence.counts).every((value) => value === 0)).toBe(true)
  expect(evidence.changes).toHaveLength(1)
  expect(evidence.changes[0].fields).toEqual([])
})
