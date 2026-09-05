import { useI18n } from '../../i18n'
import { FileText, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { AgentFile } from '../types'

export function AgentMessageAttachments({ attachments }: { attachments: AgentFile[] }) {
  const { t } = useI18n()
  const [preview, setPreview] = useState<AgentFile | null>(null)

  useEffect(() => {
    if (!preview) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [preview])

  if (attachments.length === 0) return null
  return <>
    <div className="agent-message-attachments" aria-label={t('messageFiles')}>
      {attachments.map((file) => file.mediaKind === 'image' ? <button
        aria-label={t('previewFile', { name: file.filename })}
        className="agent-message-attachments__image"
        key={file.fileId}
        onClick={() => setPreview(file)}
        type="button"
      ><img alt={file.filename} loading="lazy" src={file.contentUrl} /></button> : <a
        aria-label={t('openFile', { name: file.filename })}
        className="agent-message-attachments__document"
        href={file.contentUrl}
        key={file.fileId}
        rel="noreferrer"
        target="_blank"
      >
        <FileText aria-hidden="true" size={20} />
        <span><strong>{file.filename}</strong><small>PDF · {formatBytes(file.sizeBytes)}</small></span>
      </a>)}
    </div>
    {preview && <div
      aria-label={t('previewFile', { name: preview.filename })}
      aria-modal="true"
      className="agent-image-lightbox"
      onClick={() => setPreview(null)}
      role="dialog"
    >
      <button aria-label={t('closePreview')} autoFocus className="agent-image-lightbox__close" onClick={() => setPreview(null)} type="button"><X size={20} /></button>
      <img alt={preview.filename} onClick={(event) => event.stopPropagation()} src={preview.contentUrl} />
    </div>}
  </>
}

function formatBytes(bytes: number) {
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`
}
