import { App as AntdApp, Modal } from 'antd'
import type { ModalFuncProps } from 'antd/es/modal/interface'
import { useCallback } from 'react'

export type ConfirmDialogOptions = Omit<ModalFuncProps, 'centered' | 'classNames' | 'styles' | 'type'>

/**
 * Opens a context-aware Ant Design confirmation with the product's shared
 * positioning and keyboard-focus defaults.
 */
export function useConfirmDialog() {
  const { modal } = AntdApp.useApp()

  return useCallback((options: ConfirmDialogOptions) => {
    const confirm = typeof modal?.confirm === 'function' ? modal.confirm : Modal.confirm
    return confirm({
      ...options,
      icon: null,
      width: 520,
      centered: true,
      focusable: {
        ...options.focusable,
        autoFocusButton: options.focusable?.autoFocusButton ?? 'cancel',
      },
    })
  }, [modal])
}
