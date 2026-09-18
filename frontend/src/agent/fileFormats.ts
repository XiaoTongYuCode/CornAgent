import type { AgentFileMimeType } from './types';

export const fileExtensions: Record<AgentFileMimeType, string[]> = {
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/png': ['.png'],
  'image/webp': ['.webp'],
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'text/markdown': ['.md'],
  'text/csv': ['.csv'],
  'text/tab-separated-values': ['.tsv'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': [
    '.docx',
  ],
};

export function normalizeAgentFile(file: File): File {
  // OS MIME lookup often leaves Markdown/TSV empty or labels CSV as Excel.
  // This is a declaration only; the server validates the uploaded bytes.
  const extension = `.${file.name.split('.').pop()?.toLowerCase()}`;
  const mime = Object.entries(fileExtensions).find(([, extensions]) =>
    extensions.includes(extension),
  )?.[0];
  if (!mime || file.type === mime) return file;
  return new File([file], file.name, {
    type: mime,
    lastModified: file.lastModified,
  });
}
