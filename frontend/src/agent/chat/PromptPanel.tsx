import { Tooltip } from 'antd';
import { useI18n } from '../../i18n';
import { ArrowUp, Paperclip, Square } from 'lucide-react';
import {
  forwardRef,
  useLayoutEffect,
  useRef,
  useState,
  type ForwardedRef,
  type KeyboardEvent,
  type ClipboardEvent,
  type ReactNode,
} from 'react';
import { PromptFileTray } from './PromptFileTray';
import type { AgentDraftFile } from './useAgentFileDraft';

export interface PromptPanelSubmitPayload {
  prompt: string;
  fileIds: string[];
}

interface PromptPanelProps {
  actions?: ReactNode;
  autoFocus?: boolean;
  className?: string;
  disabled?: boolean;
  loading?: boolean;
  fileAccept?: string;
  fileInputEnabled?: boolean;
  fileProcessing?: boolean;
  fileFailed?: boolean;
  files?: AgentDraftFile[];
  fileError?: string | null;
  hasExistingFiles?: boolean;
  maxLength?: number;
  minimal?: boolean;
  onChange?: (value: string) => void;
  onFocus?: () => void;
  onAddFiles?: (files: File[]) => void;
  onRemoveFile?: (id: string) => void;
  onRetryFile?: (id: string) => void;
  onStartResearch: (
    payload: PromptPanelSubmitPayload,
  ) => Promise<boolean | void> | boolean | void;
  onStop?: () => Promise<void> | void;
  stopWhenEmpty?: boolean;
  onAlternateSubmit?: PromptPanelProps['onStartResearch'];
  placeholder?: string;
  stopLabel?: string;
  submitLabel?: string;
  submitIcon?: ReactNode;
  submitTooltip?: ReactNode;
  textareaRows?: number;
  value?: string;
}

function normalizeSingleLinePrompt(value: string): string {
  return value.replace(/\r\n?/g, '\n').replace(/\n+/g, ' ');
}

function assignTextareaRef(
  ref: ForwardedRef<HTMLTextAreaElement>,
  node: HTMLTextAreaElement | null,
) {
  if (typeof ref === 'function') ref(node);
  else if (ref) ref.current = node;
}

export const PromptPanel = forwardRef<HTMLTextAreaElement, PromptPanelProps>(
  function PromptPanel(
    {
      actions,
      autoFocus = false,
      className,
      disabled = false,
      loading = false,
      fileAccept,
      fileInputEnabled = false,
      fileProcessing = false,
      fileFailed = false,
      files = [],
      fileError,
      hasExistingFiles = false,
      maxLength = 2_000,
      minimal = false,
      onChange,
      onFocus,
      onAddFiles,
      onRemoveFile,
      onRetryFile,
      onStartResearch,
      onStop,
      stopWhenEmpty = false,
      onAlternateSubmit,
      placeholder,
      stopLabel,
      submitLabel = '',
      submitIcon,
      submitTooltip,
      textareaRows = 3,
      value,
    },
    ref,
  ) {
    const { t } = useI18n();
    const [promptState, setPromptState] = useState('');
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const rawPrompt = value ?? promptState;
    const prompt = minimal ? normalizeSingleLinePrompt(rawPrompt) : rawPrompt;
    const isStopMode =
      typeof onStop === 'function' &&
      (loading || (stopWhenEmpty && !prompt.trim() && files.length === 0));
    const readyFileIds = files
      .filter((file) => file.status === 'ready' && file.fileId)
      .map((file) => file.fileId as string);
    const hasContent = Boolean(prompt.trim()) || readyFileIds.length > 0 || hasExistingFiles;
    const canSubmit =
      isStopMode ||
      (hasContent && !disabled && !loading && !fileProcessing && !fileFailed);
    const hasSubmitLabel = Boolean(submitLabel.trim());

    useLayoutEffect(() => {
      const input = textareaRef.current;
      if (!input) return;
      if (minimal) {
        input.style.height = '24px';
        return;
      }
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    }, [minimal, prompt]);

    const setPrompt = (nextPrompt: string) => {
      const resolved = minimal
        ? normalizeSingleLinePrompt(nextPrompt)
        : nextPrompt;
      if (value === undefined) setPromptState(resolved);
      onChange?.(resolved);
    };

    const submit = async (alternate = false) => {
      if (isStopMode) {
        await onStop?.();
        return;
      }
      const nextPrompt = prompt.trim();
      if (
        (!nextPrompt && readyFileIds.length === 0 && !hasExistingFiles) ||
        disabled ||
        loading ||
        fileProcessing ||
        fileFailed
      )
        return;
      const shouldReset = await (
        alternate && onAlternateSubmit ? onAlternateSubmit : onStartResearch
      )({
        prompt: nextPrompt,
        fileIds: readyFileIds,
      });
      if (shouldReset === false) return;
      if (value === undefined) setPromptState('');
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (
        event.key !== 'Enter' ||
        (!minimal && event.shiftKey) ||
        event.nativeEvent.isComposing
      )
        return;
      event.preventDefault();
      if (canSubmit && !isStopMode) void submit(event.ctrlKey);
    };

    const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
      if (!fileInputEnabled || disabled || loading) return;
      const files = Array.from(event.clipboardData.items)
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (files.length > 0) onAddFiles?.(files);
    };

    return (
      <div
        className={[
          'prompt-panel-container',
          minimal && 'prompt-panel-container--minimal',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
      >
        <div
          className={[
            'prompt-panel',
            minimal && 'prompt-panel--minimal',
            !hasSubmitLabel && 'prompt-panel--icon-submit-only',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {!minimal && (
            <PromptFileTray
              files={files}
              onRemove={onRemoveFile ?? (() => undefined)}
              onRetry={onRetryFile ?? (() => undefined)}
            />
          )}
          {fileError && <div className="prompt-file-error" role="alert">{fileError}</div>}
          <div className="prompt-panel__input-wrapper">
            <div className="prompt-panel__editor">
              <textarea
                aria-label={t('promptInput')}
                autoFocus={autoFocus}
                className={[
                  'prompt-panel__input',
                  minimal && 'prompt-panel__input--single-row',
                ]
                  .filter(Boolean)
                  .join(' ')}
                disabled={disabled}
                maxLength={maxLength}
                onChange={(event) => setPrompt(event.target.value)}
                onFocus={onFocus}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                placeholder={placeholder ?? t('askAnything')}
                ref={(node) => {
                  textareaRef.current = node;
                  assignTextareaRef(ref, node);
                }}
                rows={minimal ? 1 : textareaRows}
                value={prompt}
                wrap={minimal ? 'off' : undefined}
              />
            </div>
            {!minimal && (
              <div className="prompt-panel__actions">
                <div
                  aria-label={t('inputOptions')}
                  className="prompt-panel__toolbar"
                  role="group"
                >
                  <button
                    className="prompt-panel__model-btn"
                    disabled
                    title={t('configuredModel')}
                    type="button"
                  >
                    {t('defaultModel')}
                  </button>
                  {fileInputEnabled && (
                    <>
                      <input
                        accept={fileAccept}
                        aria-label={t('chooseFiles')}
                        className="prompt-panel__file-input"
                        multiple
                        onChange={(event) => {
                          onAddFiles?.(Array.from(event.target.files ?? []));
                          event.target.value = '';
                        }}
                        ref={fileInputRef}
                        type="file"
                      />
                      <button
                        aria-label={t('addFiles')}
                        className="prompt-panel__tool-btn prompt-panel__attach-btn"
                        disabled={disabled || loading}
                        onClick={() => fileInputRef.current?.click()}
                        title={t('addFiles')}
                        type="button"
                      >
                        <Paperclip size={16} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </div>
                {actions}
                <PromptSubmitButton
                  icon={submitIcon}
                  tooltip={submitTooltip}
                  canSubmit={canSubmit}
                  isStopMode={isStopMode}
                  label={
                    isStopMode
                      ? (stopLabel ?? t('stopGeneration'))
                      : submitLabel
                  }
                  onClick={() => void submit()}
                />
              </div>
            )}
            {minimal && (
              <PromptSubmitButton
                icon={submitIcon}
                tooltip={submitTooltip}
                canSubmit={canSubmit}
                inline
                isStopMode={isStopMode}
                label={
                  isStopMode ? (stopLabel ?? t('stopGeneration')) : submitLabel
                }
                onClick={() => void submit()}
              />
            )}
          </div>
        </div>
      </div>
    );
  },
);

function PromptSubmitButton({
  icon,
  tooltip,
  canSubmit,
  inline = false,
  isStopMode,
  label,
  onClick,
}: {
  icon?: ReactNode;
  tooltip?: ReactNode;
  canSubmit: boolean;
  inline?: boolean;
  isStopMode: boolean;
  label: string;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const hasVisibleLabel = !isStopMode && Boolean(label.trim());
  const button = (
    <button
      aria-busy={isStopMode}
      aria-label={label || t(isStopMode ? 'stopGeneration' : 'sendMessage')}
      className={[
        'prompt-panel__submit',
        isStopMode && 'prompt-panel__submit--danger',
        hasVisibleLabel
          ? 'prompt-panel__submit--pill'
          : 'prompt-panel__submit--icon',
        inline && 'prompt-panel__submit--inline',
      ]
        .filter(Boolean)
        .join(' ')}
      disabled={!canSubmit}
      onClick={onClick}
      type="button"
    >
      {isStopMode ? (
        <Square size={16} aria-hidden />
      ) : (
        (icon ?? <ArrowUp size={16} aria-hidden />)
      )}
      {hasVisibleLabel && <span>{label}</span>}
    </button>
  );
  return tooltip && !isStopMode ? (
    <Tooltip
      title={tooltip}
      placement="topRight"
      trigger={['hover', 'focus']}
      mouseEnterDelay={1}
    >
      <span className="prompt-panel__submit-hint">{button}</span>
    </Tooltip>
  ) : (
    button
  );
}
