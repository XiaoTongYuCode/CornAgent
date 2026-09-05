import { HttpAgentTransport } from './client'

it('uses the configured API base consistently for JSON, SSE and attachment URLs', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ available: true }), { status: 200 }))
    .mockResolvedValueOnce(
      new Response('', { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    )
  vi.stubGlobal('fetch', fetchMock)
  try {
    const api = new HttpAgentTransport('https://agent.example/api/v1/')
    await expect(api.get('/agent/status')).resolves.toEqual({ available: true })
    await api.openEventStream({
      path: '/agent/runs/run-1/stream',
      signal: new AbortController().signal,
      lastEventId: '1:2',
    })
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'https://agent.example/api/v1/agent/status',
      'https://agent.example/api/v1/agent/runs/run-1/stream',
    ])
    expect(fetchMock.mock.calls[1][1].headers.get('Last-Event-ID')).toBe('1:2')
    expect(api.resolveProtectedUrl('/api/v1/files/file-1/content')).toBe(
      'https://agent.example/api/v1/files/file-1/content',
    )
    expect(api.resolveProtectedUrl('blob:preview')).toBe('blob:preview')
  } finally {
    vi.unstubAllGlobals()
  }
})
