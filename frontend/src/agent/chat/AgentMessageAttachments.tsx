import { FileFormatIcon } from '../../files/FileFormatIcon';
import { useI18n } from '../../i18n';
import { Download, ExternalLink, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import type { AgentFile } from '../types';

export function AgentMessageAttachments({
  attachments,
}: {
  attachments: AgentFile[];
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState<AgentFile | null>(null);

  useEffect(() => {
    if (!preview) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPreview(null);
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [preview]);

  if (attachments.length === 0) return null;
  return (
    <>
      <div className="agent-message-attachments" aria-label={t('messageFiles')}>
        {attachments.map((file) =>
          file.mediaKind === 'image' ? (
            <button
              aria-label={t('previewFile', { name: file.filename })}
              className="agent-message-attachments__image"
              key={file.fileId}
              onClick={() => setPreview(file)}
              type="button"
            >
              <img alt={file.filename} loading="lazy" src={file.contentUrl} />
            </button>
          ) : (
            <div
              className="agent-message-attachments__document"
              key={file.fileId}
            >
              <FileFormatIcon
                filename={file.filename}
                mimeType={file.mimeType}
                size={32}
              />
              <span className="agent-message-attachments__copy">
                <strong title={file.filename}>{file.filename}</strong>
                <small>
                  {file.filename.split('.').pop()?.toUpperCase()} ·{' '}
                  {formatBytes(file.sizeBytes)}
                </small>
              </span>
              <span className="agent-message-attachments__actions">
                <a
                  aria-label={t('openFile', { name: file.filename })}
                  title={t('openFile', { name: file.filename })}
                  href={file.contentUrl}
                  rel="noreferrer"
                  target="_blank"
                >
                  <ExternalLink aria-hidden="true" size={16} />
                </a>
                <a
                  aria-label={t('downloadFile', { name: file.filename })}
                  title={t('downloadFile', { name: file.filename })}
                  href={`${file.contentUrl}${file.contentUrl.includes('?') ? '&' : '?'}download=true`}
                  download={file.filename}
                >
                  <Download aria-hidden="true" size={16} />
                </a>
              </span>
            </div>
          ),
        )}
      </div>
      {preview && (
        <div
          aria-label={t('previewFile', { name: preview.filename })}
          aria-modal="true"
          className="agent-image-lightbox"
          onClick={() => setPreview(null)}
          role="dialog"
        >
          <button
            aria-label={t('closePreview')}
            autoFocus
            className="agent-image-lightbox__close"
            onClick={() => setPreview(null)}
            type="button"
          >
            <X size={20} />
          </button>
          <img
            alt={preview.filename}
            onClick={(event) => event.stopPropagation()}
            src={preview.contentUrl}
          />
        </div>
      )}
    </>
  );
}

function formatBytes(bytes: number) {
  return `${Math.max(1, Math.round(bytes / 1024))} KiB`;
}
