import { localizeSystemMessage } from './systemMessages'
import { translate } from './catalog'

it('formats UI messages and file limits while preserving inserted values', () => {
  expect(translate('en', 'previewFile', { name: '项目资料.pdf' })).toBe('Preview 项目资料.pdf')
  expect(localizeSystemMessage('最多可添加 4 个文件。', 'en')).toBe('You can attach up to 4 files.')
  expect(localizeSystemMessage('已思考 2 次', 'en')).toBe('Reasoned 2 times')
  expect(localizeSystemMessage('我的中文问题与模型回答', 'en')).toBe('我的中文问题与模型回答')
})
