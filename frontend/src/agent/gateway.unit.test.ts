import type { CornAgentApiTransport } from '../api/transport'
import { HttpAgentGateway } from './gateway'

it('deletes an encoded Agent session through the HTTP transport', async () => {
  const mutate = vi.fn(async () => ({ id: 'session/a', deleted: true }))
  const gateway = new HttpAgentGateway({ mutate } as unknown as CornAgentApiTransport)

  await expect(gateway.deleteSession('session/a')).resolves.toEqual({ id: 'session/a', deleted: true })
  expect(mutate).toHaveBeenCalledWith('/agent/sessions/session%2Fa', { method: 'DELETE' })
})

it('includes ordered structured file refs in the create request digest boundary', async () => {
  const mutate = vi.fn(async () => ({
    session: {
      id: 'session-1', title: 'Images', context: {}, active_leaf_message_id: null,
      created_at: '2026-09-03T00:00:00Z', updated_at: '2026-09-03T00:00:00Z',
    },
    run: {
      id: 'run-1', session_id: 'session-1', user_message_id: 'user-1',
      assistant_message_id: 'assistant-1', kind: 'create', status: 'pending',
      stream_epoch: 0, next_sequence: 0, provider_usage: {}, error_code: null,
      error_message: null, created_at: '2026-09-03T00:00:00Z',
      updated_at: '2026-09-03T00:00:00Z',
    },
  }))
  const gateway = new HttpAgentGateway({ mutate } as unknown as CornAgentApiTransport)

  await gateway.startSession('', ['file-b', 'file-a'], 'create-images')

  expect(mutate).toHaveBeenCalledWith('/agent/sessions', {
    body: { content: '', attachments: [{ file_id: 'file-b' }, { file_id: 'file-a' }] },
    idempotencyKey: 'create-images',
  }, false, undefined)
})

it('uses the private two-step upload protocol and reports the File id before PUT', async () => {
  const file = new File(['png'], 'candidate.png', { type: 'image/png' })
  const initiated = vi.fn()
  const mutate = vi.fn()
    .mockResolvedValueOnce({
      id: 'file-1', filename: file.name, mime_type: 'image/png', size_bytes: null, state: 'pending',
    })
    .mockResolvedValueOnce({
      id: 'file-1', filename: file.name, mime_type: 'image/png', size_bytes: file.size,
      state: 'stored', inspection_status: 'validated', extraction_status: 'not_requested',
    })
  const gateway = new HttpAgentGateway({ mutate } as unknown as CornAgentApiTransport)
  const controller = new AbortController()

  await expect(gateway.uploadFile(file, controller.signal, initiated)).resolves.toMatchObject({
    fileId: 'file-1',
    state: 'stored',
  })

  expect(initiated).toHaveBeenCalledWith('file-1')
  expect(mutate).toHaveBeenNthCalledWith(1, '/files', {
    body: {
      purpose: 'session_attachment',
      filename: file.name,
      mime_type: 'image/png',
      size_bytes: file.size,
    },
  }, false, controller.signal)
  expect(mutate).toHaveBeenNthCalledWith(2, '/files/file-1/content', {
    method: 'PUT',
    rawBody: file,
    contentType: 'image/png',
  }, false, controller.signal)
})

it('extracts a PDF after upload and reports the processing phase', async () => {
  const file = new File(['%PDF-1.7\n%%EOF'], 'brief.pdf', { type: 'application/pdf' })
  const phases: string[] = []
  const mutate = vi.fn()
    .mockResolvedValueOnce({
      id: 'file-pdf', filename: file.name, mime_type: file.type, size_bytes: null,
      state: 'pending',
    })
    .mockResolvedValueOnce({
      id: 'file-pdf', filename: file.name, mime_type: file.type, size_bytes: file.size,
      state: 'stored', inspection_status: 'validated', extraction_status: 'pending',
    })
    .mockResolvedValueOnce({
      id: 'file-pdf', filename: file.name, mime_type: file.type, size_bytes: file.size,
      state: 'stored', inspection_status: 'validated', extraction_status: 'ready',
    })
  const gateway = new HttpAgentGateway({ mutate } as unknown as CornAgentApiTransport)
  const controller = new AbortController()

  await expect(gateway.uploadFile(
    file,
    controller.signal,
    undefined,
    undefined,
    (phase) => phases.push(phase),
  )).resolves.toMatchObject({
    fileId: 'file-pdf',
    mediaKind: 'document',
    extractionStatus: 'ready',
  })

  expect(phases).toEqual(['uploading', 'processing'])
  expect(mutate).toHaveBeenNthCalledWith(
    3,
    '/files/file-pdf/extract',
    { body: {} },
    false,
    controller.signal,
  )
})
