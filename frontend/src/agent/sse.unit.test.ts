import { parseAgentSse } from './sse'

describe('agent SSE parser', () => {
  it('parses epoch cursors and multiline data across chunks', async () => {
    const encoder = new TextEncoder()
    const response = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('id: 2:7\nevent: reasoning_delta\ndata: {"content":'))
        controller.enqueue(encoder.encode('"先分析"}\n\nid: 2:8\nevent: done\ndata: {}\n\n'))
        controller.close()
      },
    }))
    const events = []
    for await (const event of parseAgentSse(response)) events.push(event)
    expect(events).toEqual([
      { id: '2:7', event: 'reasoning_delta', data: { content: '先分析' } },
      { id: '2:8', event: 'done', data: {} },
    ])
  })
})
