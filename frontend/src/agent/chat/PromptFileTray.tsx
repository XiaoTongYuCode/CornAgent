import { localizeSystemMessage } from '../../i18n/systemMessages'
import { useI18n } from '../../i18n'
import { FileText, LoaderCircle, RotateCcw, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { AgentDraftFile } from './useAgentFileDraft'

interface PromptFileTrayProps {
  files: AgentDraftFile[]
  onRemove: (id: string) => void
  onRetry: (id: string) => void
}

export function PromptFileTray({ files, onRemove, onRetry }: PromptFileTrayProps) {
  const { t, locale } = useI18n()
  const [preview, setPreview] = useState<AgentDraftFile | null>(null)

  useEffect(() => {
    if (!preview) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [preview])

  if (files.length === 0) return null
  return <>
    <div className="prompt-file-tray" aria-label={t('pendingFiles')}>
      {files.map((file) => <div className="prompt-file" data-kind={file.mimeType === 'application/pdf' ? 'document' : 'image'} data-status={file.status} key={file.id}>
        {file.mimeType === 'application/pdf' ? <a
          aria-label={t('openFile', { name: file.filename })}
          aria-busy={file.status === 'uploading' || file.status === 'processing'}
          className="prompt-file__preview prompt-file__preview--document"
          href={file.previewUrl}
          rel="noreferrer"
          target="_blank"
        >
          <FileText aria-hidden="true" size={24} />
          <span className="prompt-file__document-copy">
            <strong>{file.filename}</strong>
            <span>PDF · {formatBytes(file.file.size)}</span>
          </span>
        </a> : <button
          aria-label={t('previewFile', { name: file.filename })}
          aria-busy={file.status === 'uploading' || file.status === 'processing'}
          className="prompt-file__preview"
          onClick={() => setPreview(file)}
          type="button"
        >
          <img alt="" src={file.previewUrl} />
        </button>}
        {(file.status === 'uploading' || file.status === 'processing') && <span className="prompt-file__uploading" aria-hidden="true">
          <LoaderCircle className="prompt-file__spinner" size={22} />
        </span>}
        {file.status === 'error' && <span className="prompt-file__status">{t('processingFailed')}</span>}
          <span className="sr-only" role="status">
            {file.status === 'uploading'
              ? t('fileUploading', { name: file.filename })
              : file.status === 'processing'
                ? t('fileProcessing', { name: file.filename })
                : file.status === 'error'
                  ? t('fileFailed', { name: file.filename })
                  : t('fileReady', { name: file.filename })}
          </span>
        {file.status === 'error' && <button
          aria-label={t('retryFile', { name: file.filename })}
          className="prompt-file__action prompt-file__retry"
          onClick={() => onRetry(file.id)}
          title={file.error ? localizeSystemMessage(file.error, locale) : t('retryProcessing')}
          type="button"
        ><RotateCcw size={15} aria-hidden="true" /></button>}
        <button
          aria-label={t('removeFile', { name: file.filename })}
          className="prompt-file__action prompt-file__remove"
          onClick={() => onRemove(file.id)}
          type="button"
        ><X size={15} aria-hidden="true" /></button>
      </div>)}
    </div>
    {preview && <div
      aria-label={t('previewFile', { name: preview.filename })}
      aria-modal="true"
      className="agent-image-lightbox"
      onClick={() => setPreview(null)}
      role="dialog"
    >
      <button aria-label={t('closePreview')} autoFocus className="agent-image-lightbox__close" onClick={() => setPreview(null)} type="button"><X size={20} /></button>
      <img alt={preview.filename} onClick={(event) => event.stopPropagation()} src={preview.previewUrl} />
    </div>}
  </>
}

function formatBytes(bytes: number) {
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`
}
