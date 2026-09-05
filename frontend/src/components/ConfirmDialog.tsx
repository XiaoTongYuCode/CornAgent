import type { ModalFunc } from 'antd/es/modal/confirm'
import { useEffect, useEffectEvent, type ReactNode } from 'react'
import { useConfirmDialog } from './useConfirmDialog'

interface ConfirmDialogProps {
  title: ReactNode
  content?: ReactNode
  okText: ReactNode
  cancelText: ReactNode
  danger?: boolean
  errorMessage?: (error: unknown) => string
  onConfirm: () => void | Promise<void>
  onClose: () => void
}

/**
 * Declarative bridge for state-driven confirmation flows. All secondary
 * confirmations share Ant Design's context-aware modal and centered layout.
 */
export function ConfirmDialog({ title, content, okText, cancelText, danger = false, errorMessage, onConfirm, onClose }: ConfirmDialogProps) {
  const confirm = useConfirmDialog()
  const handleConfirm = useEffectEvent(async (instance: ReturnType<ModalFunc>) => {
    try {
      await onConfirm()
      onClose()
    } catch (error) {
      const message = errorMessage?.(error)
      if (message) {
        instance.update({
          content: <>{content}<div className="form-error confirm-dialog-error" role="alert">{message}</div></>,
        })
      }
      throw error
    }
  })
  const handleCancel = useEffectEvent(onClose)

  useEffect(() => {
    let cancelled = false
    let instance: ReturnType<ModalFunc> | null = null

    // StrictMode mounts, cleans up, and mounts effects again in development.
    // Deferring the imperative Ant Design call lets the first setup cancel
    // before it paints, so one state transition always owns one modal.
    queueMicrotask(() => {
      if (cancelled) return
      instance = confirm({
        title,
        content,
        okText,
        cancelText,
        // Use the semantic danger variant: LobeHub overrides legacy primary
        // button text with the monochrome theme's contrast color.
        okType: danger ? 'default' : 'primary',
        okButtonProps: danger ? { color: 'danger', variant: 'solid', style: { color: '#ffffff' } } : undefined,
        onOk: () => instance ? handleConfirm(instance) : undefined,
        onCancel: handleCancel,
      })
    })

    return () => {
      cancelled = true
      instance?.destroy()
    }
  }, [cancelText, confirm, content, danger, okText, title])

  return null
}
