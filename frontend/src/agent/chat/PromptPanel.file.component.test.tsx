import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { CornAgentApiError } from '../../api/transport'
import { I18nProvider, useI18n } from '../../i18n'

import type { AgentFileInputCapabilities, AgentUploadedFile } from '../types'
import { PromptPanel } from './PromptPanel'
import { useAgentFileDraft } from './useAgentFileDraft'

const capabilities: AgentFileInputCapabilities = {
  enabled: true,
  accepts: [
    { mimeType: 'image/jpeg', maxBytes: 5 * 1024 * 1024, maxCount: 4 },
    { mimeType: 'image/png', maxBytes: 5 * 1024 * 1024, maxCount: 4 },
    { mimeType: 'image/webp', maxBytes: 5 * 1024 * 1024, maxCount: 4 },
    { mimeType: 'application/pdf', maxBytes: 2 * 1024 * 1024, maxCount: 1 },
  ],
  maxCount: 4,
  maxTotalBytes: 16 * 1024 * 1024,
}

beforeEach(() => {
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:agent-image'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
})

function fileResult(file: File, fileId = 'file-image-1'): AgentUploadedFile {
  const document = file.type === 'application/pdf'
  return {
    fileId,
    filename: file.name,
    mimeType: document ? 'application/pdf' : 'image/png',
    sizeBytes: file.size,
    state: 'stored',
    contentUrl: `/api/v1/files/${fileId}/content`,
    scope: 'session',
    mediaKind: document ? 'document' : 'image',
    inspectionStatus: 'validated',
    extractionStatus: document ? 'ready' : 'not_requested',
  }
}

function Harness({
  upload,
  remove,
  onSubmit,
  revisionKey = 'principal:session',
}: {
  upload: (
    file: File,
    signal: AbortSignal,
    onInitiated?: (fileId: string) => void,
    existingFileId?: string,
    onPhase?: (phase: 'uploading' | 'processing') => void,
  ) => Promise<AgentUploadedFile>
  remove: (fileId: string, signal?: AbortSignal) => Promise<void>
  onSubmit: (prompt: string, fileIds: string[]) => void
  revisionKey?: string
}) {
  const draft = useAgentFileDraft({
    capabilities,
    revisionKey,
    upload,
    remove,
  })
  return <PromptPanel
    fileError={draft.error}
    fileFailed={draft.failed}
    fileInputEnabled
    fileAccept="image/png,image/jpeg,image/webp,application/pdf"
    files={draft.files}
    fileProcessing={draft.processing}
    onAddFiles={draft.addFiles}
    onRemoveFile={draft.removeFile}
    onRetryFile={draft.retryFile}
    onStartResearch={({ prompt, fileIds }) => {
      onSubmit(prompt, fileIds)
      draft.clearAfterSubmit()
      return true
    }}
  />
}

it('does not expose the unimplemented voice action from the shared prompt toolbar', () => {
  render(<Harness onSubmit={vi.fn()} remove={vi.fn(async () => undefined)} upload={vi.fn()} />)

  expect(screen.queryByRole('button', { name: '语音输入' })).not.toBeInTheDocument()
})

it('localizes upload errors without discarding files or retrying on language change', async () => {
  function Toggle() {
    const { toggleLocale } = useI18n()
    return <button onClick={toggleLocale}>Language</button>
  }
  const upload = vi.fn().mockRejectedValue(new CornAgentApiError(408, 'file_upload_timeout', 'raw upload error'))
  const remove = vi.fn(async () => undefined)
  render(<I18nProvider><Toggle /><Harness onSubmit={vi.fn()} remove={remove} upload={upload} /></I18nProvider>)
  await userEvent.upload(screen.getByLabelText('选择文件'), new File(['pdf'], 'brief.pdf', { type: 'application/pdf' }))
  expect(await screen.findByText('brief.pdf 处理失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '重试处理 brief.pdf' })).toHaveAttribute('title', '文件上传超时，请检查网络后重试。')
  await userEvent.click(screen.getByRole('button', { name: 'Language' }))
  expect(screen.getByRole('button', { name: 'Retry brief.pdf' })).toHaveAttribute('title', 'The file upload timed out. Check your connection and retry.')
  expect(upload).toHaveBeenCalledTimes(1)
  expect(remove).not.toHaveBeenCalled()
})

it('uploads and sends a pure image, then releases the local preview', async () => {
  const onSubmit = vi.fn()
  const remove = vi.fn(async () => undefined)
  const upload = vi.fn(async (file: File, _signal: AbortSignal, onInitiated?: (id: string) => void) => {
    onInitiated?.('file-image-1')
    return fileResult(file)
  })
  render(<Harness onSubmit={onSubmit} remove={remove} upload={upload} />)
  const image = new File(['png'], 'candidate.png', { type: 'image/png' })

  await userEvent.upload(screen.getByLabelText('选择文件'), image)
  expect(await screen.findByText('candidate.png 已就绪')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

  expect(onSubmit).toHaveBeenCalledWith('', ['file-image-1'])
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:agent-image')
  expect(remove).not.toHaveBeenCalled()
  expect(screen.queryByLabelText('待发送文件')).not.toBeInTheDocument()
})

it('shows PDF processing, then sends the ready PDF without prompt text', async () => {
  let finishProcessing: ((value: AgentUploadedFile) => void) | undefined
  const onSubmit = vi.fn()
  const upload = vi.fn((
    file: File,
    _signal: AbortSignal,
    onInitiated?: (id: string) => void,
    _existingFileId?: string,
    onPhase?: (phase: 'uploading' | 'processing') => void,
  ) => {
    onInitiated?.('file-pdf-1')
    onPhase?.('processing')
    return new Promise<AgentUploadedFile>((resolve) => {
      finishProcessing = resolve
      void file
    })
  })
  render(<Harness onSubmit={onSubmit} remove={vi.fn()} upload={upload} />)
  const pdf = new File(['%PDF-1.7\n%%EOF'], 'brief.pdf', { type: 'application/pdf' })

  await userEvent.upload(screen.getByLabelText('选择文件'), pdf)
  expect(await screen.findByText('brief.pdf 内容处理中')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '发送消息' })).toBeDisabled()
  expect(screen.getByRole('link', { name: '打开 brief.pdf' })).toHaveAttribute(
    'href',
    'blob:agent-image',
  )

  finishProcessing?.(fileResult(pdf, 'file-pdf-1'))
  expect(await screen.findByText('brief.pdf 已就绪')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '发送消息' }))

  expect(onSubmit).toHaveBeenCalledWith('', ['file-pdf-1'])
})

it('accepts pasted images and retries an upload without creating a second File', async () => {
  const remove = vi.fn(async () => undefined)
  const upload = vi.fn()
    .mockImplementationOnce(async (
      _file: File,
      _signal: AbortSignal,
      onInitiated?: (id: string) => void,
    ) => {
      onInitiated?.('file-retry-1')
      throw new Error('网络中断')
    })
    .mockImplementationOnce(async (file: File) => fileResult(file, 'file-retry-1'))
  render(<Harness onSubmit={vi.fn()} remove={remove} upload={upload} />)
  const image = new File(['png'], 'clipboard.png', { type: 'image/png' })

  fireEvent.paste(screen.getByLabelText('Agent 问题输入框'), {
    clipboardData: {
      items: [{ kind: 'file', getAsFile: () => image }],
    },
  })
  expect(await screen.findByText('clipboard.png 处理失败')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '重试处理 clipboard.png' }))

  expect(await screen.findByText('clipboard.png 已就绪')).toBeInTheDocument()
  expect(upload).toHaveBeenCalledTimes(2)
  expect(upload.mock.calls[1][3]).toBe('file-retry-1')
})

it('removes an unclaimed upload and revokes its object URL', async () => {
  const remove = vi.fn(async () => undefined)
  const upload = vi.fn(async (file: File) => fileResult(file))
  render(<Harness onSubmit={vi.fn()} remove={remove} upload={upload} />)
  const image = new File(['png'], 'remove.png', { type: 'image/png' })

  await userEvent.upload(screen.getByLabelText('选择文件'), image)
  await screen.findByText('remove.png 已就绪')
  await userEvent.click(screen.getByRole('button', { name: '移除 remove.png' }))

  await waitFor(() => expect(remove).toHaveBeenCalledWith('file-image-1'))
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:agent-image')
})

it('fences a late upload response after the principal or conversation changes', async () => {
  let finishUpload: ((value: AgentUploadedFile) => void) | undefined
  const remove = vi.fn(async () => undefined)
  const upload = vi.fn((file: File, _signal: AbortSignal, onInitiated?: (id: string) => void) => {
    onInitiated?.('file-late')
    return new Promise<AgentUploadedFile>((resolve) => {
      finishUpload = (value) => resolve(value)
      void file
    })
  })
  const rendered = render(
    <Harness onSubmit={vi.fn()} remove={remove} revisionKey="alice:session-a" upload={upload} />,
  )
  const image = new File(['png'], 'late.png', { type: 'image/png' })
  await userEvent.upload(screen.getByLabelText('选择文件'), image)
  expect(await screen.findByText('late.png 上传中')).toBeInTheDocument()

  rendered.rerender(
    <Harness onSubmit={vi.fn()} remove={remove} revisionKey="bob:session-b" upload={upload} />,
  )
  finishUpload?.(fileResult(image, 'file-late'))

  await waitFor(() => expect(remove).toHaveBeenCalledWith('file-late'))
  expect(screen.queryByLabelText('待发送文件')).not.toBeInTheDocument()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:agent-image')
})
