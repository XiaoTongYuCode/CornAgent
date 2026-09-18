import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { I18nProvider, useI18n } from '../i18n'
import { AgentConversation } from './AgentConversation'
import { AgentInputQueue } from './AgentInputQueue'
import type { AgentWorkspace } from './useAgentWorkspace'
import { normalizeAgentFile } from './fileFormats'
import { AgentMessageAttachments } from './chat/AgentMessageAttachments'

vi.mock('./AgentMessageList', () => ({ AgentMessageList: () => null }))

beforeEach(() => localStorage.setItem('cornagent.locale', 'en'))
afterEach(() => localStorage.removeItem('cornagent.locale'))

function workspace() {
  return {
    available: true, busy: false, error: null, fileInput: null,
    draftRevisionKey: 'p:s', snapshot: null,
    session: { id: 's', messages: [], inputs: [], activeLeafMessageId: 'a', activeRun: { id: 'r', status: 'running', assistantMessageId: 'a' } },
    send: vi.fn(), queueInput: vi.fn(async () => {}), changeInput: vi.fn(async () => {}),
    cancel: vi.fn(), uploadFile: vi.fn(), deleteFile: vi.fn(),
  } as unknown as AgentWorkspace
}

it('keeps the live composer enabled, queues Enter, steers Ctrl+Enter and does not cancel on empty Enter', async () => {
  const state = workspace()
  render(<I18nProvider><AgentConversation workspace={state} /></I18nProvider>)
  const input = screen.getByRole('textbox')
  expect(input).not.toBeDisabled()
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(state.cancel).not.toHaveBeenCalled()
  fireEvent.change(input, { target: { value: 'next task' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(state.queueInput).toHaveBeenCalledWith('next task', [], 'queue'))
  await waitFor(() => expect(input).toHaveValue(''))
  fireEvent.change(input, { target: { value: 'new direction' } })
  fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
  await waitFor(() => expect(state.queueInput).toHaveBeenCalledWith('new direction', [], 'steer'))
  expect(state.send).not.toHaveBeenCalled()
})

it('retains draft on failed queue submission and language changes', async () => {
  const state = workspace()
  vi.mocked(state.queueInput).mockRejectedValue(new Error('offline'))
  function Harness() {
    const { toggleLocale } = useI18n()
    return <><button onClick={toggleLocale}>locale</button><AgentConversation workspace={state} /></>
  }
  render(<I18nProvider><Harness /></I18nProvider>)
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'keep this' } })
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
  await screen.findByRole('alert')
  fireEvent.click(screen.getByText('locale'))
  expect(screen.getByRole('textbox')).toHaveValue('keep this')
  expect(state.queueInput).toHaveBeenCalledTimes(1)
})

it('ports queue controls with versioned mutations and pending steering state', async () => {
  const state = workspace()
  const item = { id: 'i', session_id: 's', version: 3, status: 'pending' as const, mode: 'queue' as const, content: 'queued', file_ids: [], error_message: null }
  state.session!.inputs = [item]
  render(<I18nProvider><AgentInputQueue workspace={state} onEdit={vi.fn()} /></I18nProvider>)
  fireEvent.click(screen.getByRole('button', { name: 'Steer' }))
  await waitFor(() => expect(state.changeInput).toHaveBeenCalledWith(item, { mode: 'steer' }))
  fireEvent.click(screen.getByRole('button', { name: 'Remove pending message' }))
  await waitFor(() => expect(state.changeInput).toHaveBeenCalledWith(item, { cancel: true }))
})

it('normalizes OS MIME declarations and displays document open/download actions', () => {
  expect(normalizeAgentFile(new File(['a,b'], 'Data.CSV', { type: 'application/vnd.ms-excel' })).type).toBe('text/csv')
  expect(normalizeAgentFile(new File(['# title'], 'note.md')).type).toBe('text/markdown')
  render(<I18nProvider><AgentMessageAttachments attachments={[{
    fileId: 'f', filename: 'notes.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sizeBytes: 1200,
    contentUrl: '/api/v1/files/f/content?test=1', scope: 'session', mediaKind: 'document', inspectionStatus: 'validated', extractionStatus: 'ready',
  }]} /></I18nProvider>)
  expect(screen.getByRole('link', { name: 'Open notes.docx' })).toHaveAttribute('target', '_blank')
  expect(screen.getByRole('link', { name: 'Download notes.docx' })).toHaveAttribute('href', '/api/v1/files/f/content?test=1&download=true')
})
