import { MotionProvider } from '@lobehub/ui/es/MotionProvider/index'
import { render, screen, waitFor } from '@testing-library/react'
import { motion } from 'motion/react'

import { MarkdownRenderer } from './MarkdownRenderer'

it('renders Markdown images and Mermaid diagrams through LobeHub Markdown', async () => {
  const { container } = render(
    <MotionProvider motion={motion}>
      <MarkdownRenderer
        fontSize={16}
        value={'![diagram](https://example.com/diagram.png)\n\n```mermaid\nflowchart LR\n  A[Start] --> B[Done]\n```'}
        variant="chat"
      />
    </MotionProvider>,
  )

  expect(screen.getByRole('img', { name: 'diagram' })).toHaveAttribute(
    'src',
    'https://example.com/diagram.png',
  )
  await waitFor(() => {
    expect(container.querySelector('[data-code-type="mermaid"] svg')).toBeInTheDocument()
  })
})
