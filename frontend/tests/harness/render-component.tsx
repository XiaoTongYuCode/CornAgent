import { App, ConfigProvider } from 'antd'
import { render, type RenderOptions } from '@testing-library/react'
import type { ReactElement } from 'react'

export function renderComponent(ui: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  return render(ui, {
    ...options,
    wrapper: ({ children }) => <ConfigProvider theme={{ token: { motion: false } }}>
      <App component={false}>{children}</App>
    </ConfigProvider>,
  })
}
