import FileTypeIcon from '@lobehub/ui/es/FileTypeIcon/index';

const mimeExtensions: Record<string, string> = {
  'application/pdf': 'pdf',
  'text/plain': 'txt',
  'text/csv': 'csv',
  'application/msword': 'doc',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
    'docx',
  'application/vnd.ms-excel': 'xls',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
  'application/vnd.ms-powerpoint': 'ppt',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation':
    'pptx',
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/gif': 'gif',
  'image/svg+xml': 'svg',
  'application/zip': 'zip',
  'application/json': 'json',
};

export function FileFormatIcon({
  filename,
  mimeType,
  size = 28,
}: {
  filename: string;
  mimeType?: string;
  size?: number;
}) {
  const extension =
    /\.([a-z0-9]+)$/i.exec(filename)?.[1].toLowerCase() ||
    mimeExtensions[mimeType?.split(';')[0].trim().toLowerCase() ?? ''] ||
    'file';
  const color =
    extension === 'pdf'
      ? '#e54d42'
      : /^(docx?|txt|md)$/.test(extension)
        ? '#3875cb'
        : /^(xlsx?|csv)$/.test(extension)
          ? '#278557'
          : /^(pptx?)$/.test(extension)
            ? '#d56b35'
            : /^(png|jpe?g|gif|webp|svg|avif|heic)$/.test(extension)
              ? '#8c5bc7'
              : /^(zip|rar|7z|gz|tar)$/.test(extension)
                ? '#b48428'
                : '#687787';
  return (
    <span className="file-format-icon" aria-hidden="true">
      <FileTypeIcon
        filetype={extension}
        color={color}
        size={size}
        variant="color"
      />
    </span>
  );
}
