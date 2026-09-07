import { describe, expect, it } from 'vitest'
import { apiErrorMessage, CornAgentApiError } from './transport'

describe('localized API errors', () => {
  it.each([
    [408, 'file_upload_timeout', '文件上传超时'],
    [503, 'file_operations_busy', '文件处理繁忙'],
    [409, 'agent_question_already_resolved', '该问题已处理'],
    [422, 'session_file_extraction_timeout', 'PDF 内容提取超时'],
    [429, 'agent_run_rate_limited', '操作过于频繁'],
    [503, 'internal_error', '服务暂时不可用'],
  ])('uses the business code before HTTP status for %s / %s', (status, code, expected) => {
    const error = new CornAgentApiError(status, code, 'raw server diagnostic')
    expect(apiErrorMessage(error, 'fallback', (zh) => zh)).toContain(expected)
    expect(apiErrorMessage(error, 'fallback')).not.toContain('raw server diagnostic')
  })

  it('handles network failures and preserves caller fallback for unknown errors', () => {
    expect(apiErrorMessage(new TypeError('Failed to fetch'), 'fallback')).toContain('network request failed')
    expect(apiErrorMessage(new Error('custom'), 'localized custom')).toBe('localized custom')
  })
})
