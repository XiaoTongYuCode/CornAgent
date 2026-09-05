import { useI18n } from '../../i18n'
import { localizeSystemMessage } from '../../i18n/systemMessages'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { createClientId } from '../../client-id'
import type { AgentFileInputCapabilities, AgentUploadedFile } from '../types'

export type AgentDraftFileStatus = 'uploading' | 'processing' | 'ready' | 'error'

export interface AgentDraftFile {
  id: string
  file: File
  fileId: string | null
  filename: string
  mimeType: string
  previewUrl: string
  status: AgentDraftFileStatus
  error: string | null
}

interface UseAgentFileDraftOptions {
  capabilities: AgentFileInputCapabilities | null
  revisionKey: string
  upload: (
    file: File,
    signal: AbortSignal,
    onInitiated?: (fileId: string) => void,
    existingFileId?: string,
    onPhase?: (phase: 'uploading' | 'processing') => void,
  ) => Promise<AgentUploadedFile>
  remove: (fileId: string, signal?: AbortSignal) => Promise<void>
}

export function useAgentFileDraft({
  capabilities,
  revisionKey,
  upload,
  remove,
}: UseAgentFileDraftOptions) {
  const { locale } = useI18n()
  const [files, setFiles] = useState<AgentDraftFile[]>([])
  const [error, setError] = useState<string | null>(null)
  const filesRef = useRef<AgentDraftFile[]>([])
  const controllers = useRef(new Map<string, AbortController>())
  const revision = useRef(0)

  const replaceFiles = useCallback((update: (current: AgentDraftFile[]) => AgentDraftFile[]) => {
    setFiles((current) => {
      const next = update(current)
      filesRef.current = next
      return next
    })
  }, [])

  const dispose = useCallback((deleteUploads: boolean) => {
    revision.current += 1
    controllers.current.forEach((controller) => controller.abort())
    controllers.current.clear()
    const current = filesRef.current
    filesRef.current = []
    setFiles([])
    setError(null)
    current.forEach((file) => {
      URL.revokeObjectURL(file.previewUrl)
      if (deleteUploads && file.fileId) {
        void remove(file.fileId).catch(() => undefined)
      }
    })
  }, [remove])

  useEffect(() => {
    dispose(true)
    return () => dispose(true)
  }, [dispose, revisionKey])

  const uploadItem = useCallback(async (item: AgentDraftFile, existingFileId?: string) => {
    const itemRevision = revision.current
    const controller = new AbortController()
    controllers.current.get(item.id)?.abort()
    controllers.current.set(item.id, controller)
    replaceFiles((current) => current.map((candidate) => candidate.id === item.id
      ? { ...candidate, status: 'uploading', error: null }
      : candidate))
    try {
      const uploaded = await upload(
        item.file,
        controller.signal,
        (fileId) => {
          if (revision.current !== itemRevision || controller.signal.aborted) return
          replaceFiles((current) => current.map((candidate) => candidate.id === item.id
            ? { ...candidate, fileId }
            : candidate))
        },
        existingFileId,
        (phase) => {
          if (revision.current !== itemRevision || controller.signal.aborted) return
          replaceFiles((current) => current.map((candidate) => candidate.id === item.id
            ? { ...candidate, status: phase }
            : candidate))
        },
      )
      if (revision.current !== itemRevision || controller.signal.aborted) return
      replaceFiles((current) => current.map((candidate) => candidate.id === item.id
        ? {
          ...candidate,
          fileId: uploaded.fileId,
          filename: uploaded.filename,
          mimeType: uploaded.mimeType,
          status: 'ready',
          error: null,
        }
        : candidate))
    } catch (reason) {
      if (revision.current !== itemRevision || controller.signal.aborted) return
      replaceFiles((current) => current.map((candidate) => candidate.id === item.id
        ? {
          ...candidate,
          status: 'error',
          error: reason instanceof Error ? reason.message : '文件处理失败。',
        }
        : candidate))
    } finally {
      if (controllers.current.get(item.id) === controller) controllers.current.delete(item.id)
    }
  }, [replaceFiles, upload])

  const addFiles = useCallback((files: File[]) => {
    if (!capabilities?.enabled || files.length === 0) return
    const accepted: AgentDraftFile[] = []
    let totalBytes = filesRef.current.reduce((total, file) => total + file.file.size, 0)
    for (const file of files) {
      if (filesRef.current.length + accepted.length >= capabilities.maxCount) {
        setError(`最多可添加 ${capabilities.maxCount} 个文件。`)
        break
      }
      const constraint = capabilities.accepts.find((item) => item.mimeType === file.type)
      if (!constraint) {
        setError(`不支持 ${file.name} 的文件格式。`)
        continue
      }
      const sameTypeCount = [...filesRef.current, ...accepted]
        .filter((item) => item.mimeType === file.type).length
      if (sameTypeCount >= constraint.maxCount) {
        setError(file.type === 'application/pdf'
          ? `最多可添加 ${constraint.maxCount} 个 PDF。`
          : `此格式最多可添加 ${constraint.maxCount} 个文件。`)
        continue
      }
      if (file.size > constraint.maxBytes) {
        setError(`${file.name} 不能超过 ${formatBytes(constraint.maxBytes)}。`)
        continue
      }
      if (totalBytes + file.size > capabilities.maxTotalBytes) {
        setError(`文件合计不能超过 ${formatBytes(capabilities.maxTotalBytes)}。`)
        break
      }
      totalBytes += file.size
      accepted.push({
        id: createClientId(),
        file,
        fileId: null,
        filename: file.name,
        mimeType: file.type,
        previewUrl: URL.createObjectURL(file),
        status: 'uploading',
        error: null,
      })
    }
    if (accepted.length === 0) return
    setError(null)
    replaceFiles((current) => [...current, ...accepted])
    accepted.forEach((item) => { void uploadItem(item) })
  }, [capabilities, replaceFiles, uploadItem])

  const removeFile = useCallback((id: string) => {
    const target = filesRef.current.find((file) => file.id === id)
    if (!target) return
    controllers.current.get(id)?.abort()
    controllers.current.delete(id)
    URL.revokeObjectURL(target.previewUrl)
    replaceFiles((current) => current.filter((file) => file.id !== id))
    if (target.fileId) void remove(target.fileId).catch(() => undefined)
  }, [remove, replaceFiles])

  const retryFile = useCallback((id: string) => {
    const target = filesRef.current.find((file) => file.id === id)
    if (!target || target.status !== 'error') return
    void uploadItem(target, target.fileId ?? undefined)
  }, [uploadItem])

  const clearAfterSubmit = useCallback(() => dispose(false), [dispose])
  const readyFileIds = useMemo(
    () => files.filter((file) => file.status === 'ready' && file.fileId).map((file) => file.fileId as string),
    [files],
  )
  const processing = files.some((file) => file.status === 'uploading' || file.status === 'processing')
  const failed = files.some((file) => file.status === 'error')

  return {
    files,
    error: error ? localizeSystemMessage(error, locale) : null,
    addFiles,
    removeFile,
    retryFile,
    clearAfterSubmit,
    readyFileIds,
    processing,
    failed,
  }
}

function formatBytes(bytes: number) {
  return `${Math.round(bytes / (1024 * 1024))} MiB`
}
