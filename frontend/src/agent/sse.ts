import type { AgentSseEvent } from './types'

export async function* parseAgentSse(response: Response): AsyncGenerator<AgentSseEvent> {
  if (!response.body) throw new Error('Agent stream has no response body.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const parsed = parseFrame(frame)
      if (parsed) yield parsed
    }
    if (done) break
  }
  const tail = parseFrame(buffer)
  if (tail) yield tail
}

function parseFrame(frame: string): AgentSseEvent | null {
  if (!frame.trim() || frame.startsWith(':')) return null
  let id = ''
  let event = ''
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('id:')) id = line.slice(3).trim()
    else if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (!id || !event || data.length === 0) return null
  return { id, event, data: JSON.parse(data.join('\n')) } as AgentSseEvent
}
