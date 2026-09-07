import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createClientId } from '../client-id'
import { apiErrorMessage } from '../api/transport'
import { HttpAgentGateway, toRun, toSnapshot } from './gateway'
import type { AgentContentPart, AgentFileInputCapabilities, AgentMessage, AgentQuestionResponse, AgentRun, AgentSession, AgentSessionDetail, AgentSessionPage, AgentSnapshot, AgentSseEvent, AgentUploadedFile } from './types'

const TERMINAL = new Set<AgentRun['status']>(['completed', 'failed', 'cancelled'])

function upsertPart(parts: AgentContentPart[], part: AgentContentPart) {
  const index = parts.findIndex((item) => item.id === part.id)
  if (index < 0) return [...parts, part]
  const next = [...parts]
  next[index] = part
  return next
}

function appendPart(
  parts: AgentContentPart[],
  id: string,
  kind: 'markdown' | 'reasoning',
  content: string,
  title?: string | null,
) {
  const current = parts.find((part) => part.id === id)
  return upsertPart(parts, {
    id, kind, title: title ?? (kind === 'reasoning' ? '正在思考' : undefined),
    content: `${current?.content ?? ''}${content}`,
  })
}

function mergeMessages(...collections: AgentMessage[][]) {
  return Array.from(
    new Map(collections.flat().map((message) => [message.id, message])).values(),
  ).sort((left, right) => left.createdAt.localeCompare(right.createdAt) || left.id.localeCompare(right.id))
}

export interface AgentWorkspace {
  open: boolean
  available: boolean | null
  fileInput: AgentFileInputCapabilities | null
  draftRevisionKey: string
  sessions: AgentSession[]
  session: AgentSessionDetail | null
  snapshot: AgentSnapshot | null
  busy: boolean
  loadingOlder: boolean
  loadingMoreSessions: boolean
  sessionsNextCursor: string | null
  error: string | null
  setOpen(open: boolean): void
  ask(content: string, fileIds?: string[]): Promise<string>
  send(content: string, fileIds?: string[]): Promise<string>
  uploadFile(file: File, signal: AbortSignal, onInitiated?: (fileId: string) => void, existingFileId?: string, onPhase?: (phase: 'uploading' | 'processing') => void): Promise<AgentUploadedFile>
  deleteFile(fileId: string, signal?: AbortSignal): Promise<void>
  newSession(): Promise<string | null>
  selectSession(id: string): Promise<void>
  deleteSession(id: string): Promise<void>
  loadMoreSessions(): Promise<void>
  searchSessions(query: string, cursor?: string | null): Promise<AgentSessionPage>
  loadOlder(): Promise<void>
  respond(questionId: string, payload: AgentQuestionResponse, idempotencyKey: string): Promise<void>
  cancel(): Promise<void>
  regenerate(messageId: string): Promise<void>
  edit(messageId: string, content: string): Promise<void>
  switchVersion(messageId: string): Promise<void>
}

export function useAgentWorkspace(
  gateway: HttpAgentGateway | null,
  principalKey: string,
  routeSessionId: string | null | undefined = undefined,
): AgentWorkspace {
  const [open, setOpen] = useState(false)
  const [available, setAvailable] = useState<boolean | null>(null)
  const [fileInput, setFileInput] = useState<AgentFileInputCapabilities | null>(null)
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [session, setSession] = useState<AgentSessionDetail | null>(null)
  const [snapshot, setSnapshot] = useState<AgentSnapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false)
  const [sessionsNextCursor, setSessionsNextCursor] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [streamRevision, setStreamRevision] = useState(0)
  const streamCursor = useRef<string | undefined>(undefined)
  const principalRevision = useRef(0)
  const sessionListLoadRevision = useRef(0)
  const sessionIdRef = useRef<string | null>(null)
  const loadedSessionIdRef = useRef<string | null>(null)
  const sessionLoadRevision = useRef(0)
  const versionActionRevision = useRef(0)
  const sessionMutationRevision = useRef(0)
  const startPromiseRef = useRef<Promise<string> | null>(null)
  const startAbortController = useRef<AbortController | null>(null)

  useLayoutEffect(() => {
    principalRevision.current += 1
    versionActionRevision.current += 1
    sessionMutationRevision.current += 1
    startAbortController.current?.abort()
    startAbortController.current = null
    return () => {
      principalRevision.current += 1
      versionActionRevision.current += 1
      sessionMutationRevision.current += 1
      startAbortController.current?.abort()
      startAbortController.current = null
    }
  }, [principalKey])

  const refreshSessions = useCallback(async () => {
    if (!gateway) return []
    const expectedPrincipalRevision = principalRevision.current
    const revision = ++sessionListLoadRevision.current
    const page = await gateway.listSessions()
    if (principalRevision.current !== expectedPrincipalRevision || sessionListLoadRevision.current !== revision) {
      return []
    }
    setSessions(page.data)
    setSessionsNextCursor(page.nextCursor)
    return page.data
  }, [gateway])

  const loadMoreSessions = useCallback(async () => {
    if (!gateway || !sessionsNextCursor || loadingMoreSessions) return
    setLoadingMoreSessions(true)
    setError(null)
    const expectedPrincipalRevision = principalRevision.current
    const revision = ++sessionListLoadRevision.current
    try {
      const page = await gateway.listSessions(sessionsNextCursor)
      if (principalRevision.current !== expectedPrincipalRevision || sessionListLoadRevision.current !== revision) {
        return
      }
      setSessions((current) => {
        const byId = new Map(current.map((item) => [item.id, item]))
        page.data.forEach((item) => byId.set(item.id, item))
        return [...byId.values()]
      })
      setSessionsNextCursor(page.nextCursor)
    } catch (reason) {
      if (
        principalRevision.current === expectedPrincipalRevision
        && sessionListLoadRevision.current === revision
      ) setError(apiErrorMessage(reason, reason instanceof Error ? reason.message : '无法加载更多对话。'))
    } finally {
      setLoadingMoreSessions(false)
    }
  }, [gateway, loadingMoreSessions, sessionsNextCursor])

  const searchSessions = useCallback(async (query: string, cursor?: string | null) => {
    if (!gateway) return { data: [], nextCursor: null }
    const expectedPrincipalRevision = principalRevision.current
    const page = await gateway.listSessions(cursor, query)
    return principalRevision.current === expectedPrincipalRevision ? page : { data: [], nextCursor: null }
  }, [gateway])

  const refreshSession = useCallback(async (sessionId: string) => {
    if (!gateway) return null
    const revision = ++sessionLoadRevision.current
    const detail = await gateway.getSession(sessionId)
    if (sessionLoadRevision.current !== revision || sessionIdRef.current !== sessionId) {
      return null
    }
    loadedSessionIdRef.current = detail.id
    setSession(detail)
    return detail
  }, [gateway])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) return
      setOpen(false)
      setAvailable(null)
      setFileInput(null)
      sessionListLoadRevision.current += 1
      setSessions([])
      setSessionsNextCursor(null)
      setSession(null)
      sessionLoadRevision.current += 1
      sessionIdRef.current = null
      loadedSessionIdRef.current = null
      setSnapshot(null)
      setBusy(false)
      setLoadingOlder(false)
      setLoadingMoreSessions(false)
      setError(null)
      streamCursor.current = undefined
      startPromiseRef.current = null
    })
    return () => { active = false }
  }, [principalKey])

  useEffect(() => {
    if (routeSessionId !== undefined && routeSessionId !== sessionIdRef.current) {
      startAbortController.current?.abort()
      startAbortController.current = null
      sessionLoadRevision.current += 1
      sessionListLoadRevision.current += 1
      versionActionRevision.current += 1
      sessionMutationRevision.current += 1
      sessionIdRef.current = routeSessionId
      loadedSessionIdRef.current = null
      setSession(null)
      setSnapshot(null)
      setBusy(false)
      setError(null)
      streamCursor.current = undefined
    }
    if (!gateway) {
      queueMicrotask(() => setAvailable(false))
      return
    }
    let active = true
    void gateway.status().then(async (status) => {
      if (!active) return
      setAvailable(status.available)
      setFileInput(status.fileInput ?? null)
      if (!status.available) return
      const items = await refreshSessions()
      if (!active) return
      if (routeSessionId === null) {
        return
      }
      const targetId = routeSessionId ?? (open ? sessionIdRef.current ?? items[0]?.id ?? null : null)
      if (targetId && targetId !== loadedSessionIdRef.current) {
        sessionIdRef.current = targetId
        loadedSessionIdRef.current = null
        setSession(null)
        setSnapshot(null)
        streamCursor.current = undefined
        await refreshSession(targetId)
      }
    }).catch((reason: unknown) => {
      if (active) setError(apiErrorMessage(reason, reason instanceof Error ? reason.message : 'Agent 状态读取失败。'))
    })
    return () => { active = false }
  }, [gateway, open, principalKey, refreshSession, refreshSessions, routeSessionId])

  const runId = snapshot?.run.id ?? session?.activeRun?.id ?? null
  useEffect(() => {
    const engaged = open || (Boolean(routeSessionId) && routeSessionId === session?.id)
    if (!gateway || !runId || !engaged) return
    const controller = new AbortController()
    let retryDelay = 250
    const consume = async () => {
      while (!controller.signal.aborted) {
        try {
          let terminal = false
          for await (const event of gateway.stream(runId, controller.signal, streamCursor.current)) {
            streamCursor.current = event.id
            terminal = applyEvent(event, setSnapshot)
            if (terminal) break
          }
          if (terminal) {
            const currentSessionId = session?.id
            if (currentSessionId) await refreshSession(currentSessionId)
            await refreshSessions()
            return
          }
          retryDelay = 250
        } catch (reason) {
          if (controller.signal.aborted) return
          setError(apiErrorMessage(reason, reason instanceof Error ? reason.message : 'Agent 连接中断，正在恢复。'))
          await new Promise((resolve) => window.setTimeout(resolve, retryDelay))
          retryDelay = Math.min(retryDelay * 2, 2_000)
        }
      }
    }
    void consume()
    return () => controller.abort()
  }, [gateway, open, principalKey, refreshSession, refreshSessions, routeSessionId, runId, session?.id, streamRevision])

  const start = useCallback((content: string, fileIds: string[] = [], options?: { createNew?: boolean; target?: AgentSessionDetail | null }) => {
    if (!gateway) throw new Error('当前客户端不支持 Agent。')
    if (startPromiseRef.current) return startPromiseRef.current

    const operation = (async () => {
      const initialLoadRevision = sessionLoadRevision.current
      const controller = new AbortController()
      startAbortController.current?.abort()
      startAbortController.current = controller
      setBusy(true)
      setError(null)
      try {
        const status = await gateway.status(controller.signal)
        setAvailable(status.available)
        setFileInput(status.fileInput ?? null)
        if (!status.available) throw new Error('CornAgent 尚未配置模型和 Redis。')
        const routedSessionId = routeSessionId ?? null
        const targetSessionId = options?.createNew
          ? null
          : routeSessionId === null
            ? null
            : options?.target?.id ?? routedSessionId ?? session?.id ?? null
        let sessionId: string
        let run: AgentRun
        if (targetSessionId) {
          sessionId = targetSessionId
          run = await gateway.startRun(sessionId, content, fileIds, controller.signal)
        } else {
          const created = await gateway.startSession(content, fileIds, createClientId(), controller.signal)
          sessionId = created.session.id
          run = created.run
        }
        if (sessionLoadRevision.current !== initialLoadRevision) {
          await refreshSessions()
          return sessionId
        }
        streamCursor.current = undefined
        sessionIdRef.current = sessionId
        setSnapshot(null)
        const refreshed = await refreshSession(sessionId)
        if (refreshed) {
          setSession({ ...refreshed, activeRun: run, activeLeafMessageId: run.assistantMessageId })
          setStreamRevision((value) => value + 1)
        }
        await refreshSessions()
        return sessionId
      } finally {
        if (startAbortController.current === controller) startAbortController.current = null
        setBusy(false)
      }
    })()
    startPromiseRef.current = operation
    const releaseOperation = () => {
      if (startPromiseRef.current === operation) startPromiseRef.current = null
    }
    void operation.then(releaseOperation, releaseOperation)
    return operation
  }, [gateway, refreshSession, refreshSessions, routeSessionId, session])

  const ask = useCallback(async (content: string, fileIds: string[] = []) => {
    try { return await start(content, fileIds, { createNew: true }) } catch (reason) {
      const failure = reason instanceof Error ? reason : new Error('无法开始 Agent 对话。')
      if (failure.name !== 'AbortError') setError(apiErrorMessage(failure, failure.message))
      throw failure
    }
  }, [start])

  const uploadFile = useCallback((file: File, signal: AbortSignal, onInitiated?: (fileId: string) => void, existingFileId?: string, onPhase?: (phase: 'uploading' | 'processing') => void) => {
    if (!gateway) throw new Error('当前客户端不支持文件上传。')
    return gateway.uploadFile(file, signal, onInitiated, existingFileId, onPhase)
  }, [gateway])

  const deleteFile = useCallback(async (fileId: string, signal?: AbortSignal) => {
    if (!gateway) return
    await gateway.deleteFile(fileId, signal)
  }, [gateway])

  const newSession = useCallback(() => {
    if (!gateway) return Promise.resolve(null)
    startAbortController.current?.abort()
    startAbortController.current = null
    sessionLoadRevision.current += 1
    versionActionRevision.current += 1
    sessionMutationRevision.current += 1
    sessionIdRef.current = null
    loadedSessionIdRef.current = null
    setSession(null)
    setSnapshot(null)
    setBusy(false)
    setError(null)
    streamCursor.current = undefined
    return Promise.resolve(null)
  }, [gateway])

  const selectSession = useCallback(async (id: string) => {
    startAbortController.current?.abort()
    startAbortController.current = null
    versionActionRevision.current += 1
    sessionMutationRevision.current += 1
    setBusy(true)
    try {
      setSnapshot(null)
      streamCursor.current = undefined
      sessionIdRef.current = id
      loadedSessionIdRef.current = null
      await refreshSession(id)
      setStreamRevision((value) => value + 1)
    } finally { setBusy(false) }
  }, [refreshSession])

  const deleteSession = useCallback(async (id: string) => {
    if (!gateway) throw new Error('当前客户端不支持删除会话。')
    const expectedPrincipalRevision = principalRevision.current
    const revision = ++sessionMutationRevision.current
    setBusy(true)
    setError(null)
    try {
      await gateway.deleteSession(id)
      if (principalRevision.current !== expectedPrincipalRevision) return
      setSessions((current) => current.filter((item) => item.id !== id))
      if (sessionMutationRevision.current !== revision || sessionIdRef.current !== id) return
      sessionLoadRevision.current += 1
      versionActionRevision.current += 1
      sessionIdRef.current = null
      loadedSessionIdRef.current = null
      setSession(null)
      setSnapshot(null)
      streamCursor.current = undefined
    } catch (reason) {
      const failure = reason instanceof Error ? reason : new Error('无法删除会话。')
      if (
        principalRevision.current === expectedPrincipalRevision
        && sessionMutationRevision.current === revision
        && sessionIdRef.current === id
      ) setError(apiErrorMessage(failure, failure.message))
      throw failure
    } finally {
      if (
        principalRevision.current === expectedPrincipalRevision
        && sessionMutationRevision.current === revision
      ) setBusy(false)
    }
  }, [gateway])

  const loadOlder = useCallback(async () => {
    const current = session
    if (!gateway || !current?.nextBefore || loadingOlder) return
    const expectedSessionLoadRevision = sessionLoadRevision.current
    setLoadingOlder(true)
    setError(null)
    try {
      const older = await gateway.getSession(current.id, current.nextBefore)
      setSession((latest) => latest?.id === current.id ? {
        ...latest,
        messages: [...older.messages, ...latest.messages],
        nextBefore: older.nextBefore,
      } : latest)
    } catch (reason) {
      if (
        sessionLoadRevision.current === expectedSessionLoadRevision
        && sessionIdRef.current === current.id
      ) setError(apiErrorMessage(reason, reason instanceof Error ? reason.message : '无法加载更早消息。'))
    } finally {
      setLoadingOlder(false)
    }
  }, [gateway, loadingOlder, session])

  const respond = useCallback(async (questionId: string, payload: AgentQuestionResponse, key: string) => {
    if (!gateway) return
    await gateway.respond(questionId, payload, key)
    setStreamRevision((value) => value + 1)
  }, [gateway])

  const cancel = useCallback(async () => {
    if (!gateway || !runId) return
    await gateway.cancel(runId)
    setStreamRevision((value) => value + 1)
  }, [gateway, runId])

  const runVersionAction = useCallback(async (expectedSessionId: string, action: () => Promise<AgentRun>) => {
    if (!gateway) return
    const expectedPrincipalRevision = principalRevision.current
    const revision = ++versionActionRevision.current
    setBusy(true)
    setError(null)
    try {
      const run = await action()
      if (
        principalRevision.current !== expectedPrincipalRevision
        || versionActionRevision.current !== revision
        || sessionIdRef.current !== expectedSessionId
        || run.sessionId !== expectedSessionId
      ) return
      const refreshed = await gateway.getSession(expectedSessionId)
      if (
        principalRevision.current !== expectedPrincipalRevision
        || versionActionRevision.current !== revision
        || sessionIdRef.current !== expectedSessionId
        || run.sessionId !== expectedSessionId
        || refreshed.id !== expectedSessionId
      ) return
      if (
        refreshed.activeLeafMessageId !== run.assistantMessageId
        || !refreshed.messages.some((message) => message.id === run.assistantMessageId)
      ) {
        throw new Error('消息分支状态尚未同步，请刷新会话后重试。')
      }
      setSnapshot(null)
      streamCursor.current = undefined
      setSession((current) => current?.id === expectedSessionId
        ? { ...refreshed, messages: mergeMessages(current.messages, refreshed.messages) }
        : current)
      setStreamRevision((value) => value + 1)
    } finally {
      if (versionActionRevision.current === revision) setBusy(false)
    }
  }, [gateway])

  const switchMessageVersion = useCallback(async (messageId: string) => {
    const expectedSessionId = session?.id
    if (!gateway || !expectedSessionId || sessionIdRef.current !== expectedSessionId) return
    const expectedPrincipalRevision = principalRevision.current
    const revision = ++versionActionRevision.current
    setBusy(true)
    try {
      const switched = await gateway.switchVersion(expectedSessionId, messageId)
      if (
        principalRevision.current !== expectedPrincipalRevision
        || versionActionRevision.current !== revision
        || sessionIdRef.current !== expectedSessionId
        || switched.id !== expectedSessionId
      ) return
      setSession((current) => current?.id === expectedSessionId ? {
        ...switched,
        messages: mergeMessages(current.messages, switched.messages),
      } : current)
      setSnapshot(null)
    } finally {
      if (versionActionRevision.current === revision) setBusy(false)
    }
  }, [gateway, session?.id])

  return useMemo(() => ({
    open, available, fileInput, draftRevisionKey: `${principalKey}:${session?.id ?? 'new'}`, sessions, session, snapshot, busy, loadingOlder, loadingMoreSessions,
    sessionsNextCursor, error, setOpen, ask, send: start, newSession, selectSession,
    deleteSession, uploadFile, deleteFile, loadMoreSessions, searchSessions, loadOlder, respond, cancel,
    regenerate: (messageId: string) => {
      const expectedSessionId = session?.id
      if (!gateway || !expectedSessionId) return Promise.resolve()
      return runVersionAction(expectedSessionId, () => gateway.regenerate(messageId))
    },
    edit: (messageId: string, content: string) => {
      const expectedSessionId = session?.id
      if (!gateway || !expectedSessionId) return Promise.resolve()
      return runVersionAction(expectedSessionId, () => gateway.edit(messageId, content))
    },
    switchVersion: switchMessageVersion,
  }), [available, ask, busy, cancel, deleteFile, deleteSession, error, fileInput, gateway, loadMoreSessions, loadOlder, loadingMoreSessions, loadingOlder, newSession, open, principalKey, respond, runVersionAction, searchSessions, selectSession, session, sessions, sessionsNextCursor, snapshot, start, switchMessageVersion, uploadFile])
}

export function applyEvent(
  event: AgentSseEvent,
  setSnapshot: React.Dispatch<React.SetStateAction<AgentSnapshot | null>>,
): boolean {
  if (event.event === 'snapshot') {
    setSnapshot(toSnapshot(event.data as never))
    return TERMINAL.has((event.data.run as { status: AgentRun['status'] }).status)
  }
  if (event.event === 'session' && event.data.run) {
    const run = toRun(event.data.run as Parameters<typeof toRun>[0])
    setSnapshot((current) => current && current.run.id === run.id ? { ...current, run } : current)
    return TERMINAL.has(run.status)
  }
  if (event.event === 'delta' || event.event === 'reasoning_delta') {
    const content = String(event.data.content ?? '')
    const partContent = typeof event.data.part_content === 'string' ? event.data.part_content : content
    const partId = String(event.data.part_id ?? '')
    const kind = event.data.kind === 'markdown' || event.data.kind === 'reasoning'
      ? event.data.kind
      : event.event === 'delta' ? 'markdown' : 'reasoning'
    const title = typeof event.data.title === 'string' ? event.data.title : null
    setSnapshot((current) => current ? {
      ...current,
      draftMarkdown: event.event === 'delta' ? `${current.draftMarkdown}${content}` : current.draftMarkdown,
      reasoningMarkdown: event.event === 'reasoning_delta' ? `${current.reasoningMarkdown}${content}` : current.reasoningMarkdown,
      contentParts: appendPart(current.contentParts, partId, kind, partContent, title),
    } : current)
    return false
  }
  if (event.event === 'user_question' || event.event === 'tool_call') {
    const part = event.data as unknown as AgentContentPart
    setSnapshot((current) => current ? { ...current, contentParts: upsertPart(current.contentParts, part) } : current)
    return false
  }
  if (event.event === 'done') {
    const parts = event.data.content_parts as AgentContentPart[] | undefined
    setSnapshot((current) => current ? {
      ...current, contentParts: parts ?? current.contentParts,
      run: { ...current.run, status: 'completed' },
    } : current)
    return true
  }
  if (event.event === 'error' || event.event === 'cancelled') {
    setSnapshot((current) => current ? {
      ...current,
      run: {
        ...current.run,
        status: event.event === 'cancelled' ? 'cancelled' : 'failed',
        errorCode: typeof event.data.code === 'string' ? event.data.code : current.run.errorCode,
        errorMessage: typeof event.data.message === 'string' ? event.data.message : current.run.errorMessage,
      },
    } : current)
    return true
  }
  return false
}
