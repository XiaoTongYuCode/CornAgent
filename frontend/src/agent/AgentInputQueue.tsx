import { useState } from 'react';
import { Dropdown, Tooltip } from 'antd';
import { AnimatePresence } from 'motion/react';
import { AnimatedMessageBody } from './chat/AnimatedMessageBody';
import {
  ListEnd,
  ListTree,
  CornerDownRight,
  Trash2,
  Ellipsis,
  Pencil,
  RotateCcw,
} from 'lucide-react';
import { apiErrorMessage } from '../api/transport';
import { useI18n } from '../i18n';
import type { AgentInput } from './types';
import type { AgentWorkspace } from './useAgentWorkspace';

export function AgentInputQueue({
  workspace,
  onEdit,
  disabled = false,
}: {
  workspace: AgentWorkspace;
  onEdit: (input: AgentInput) => Promise<void>;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const inputs = workspace.session?.inputs ?? [];
  return (
    <AnimatePresence initial={false}>
      {inputs.length > 0 && (
        <AnimatedMessageBody
          key="queue"
          className="agent-input-queue-motion"
          motionPreset="accordion"
        >
          <section
            className="agent-input-queue"
            aria-label={t('inputQueue1')}
          >
            {inputs.map((input) => (
              <QueuedInput
                key={input.id}
                input={input}
                change={workspace.changeInput}
                onEdit={onEdit}
                disabled={disabled}
              />
            ))}
          </section>
        </AnimatedMessageBody>
      )}
    </AnimatePresence>
  );
}
function QueuedInput({
  input,
  change,
  onEdit,
  disabled,
}: {
  input: AgentInput;
  change: AgentWorkspace['changeInput'];
  onEdit: (input: AgentInput) => Promise<void>;
  disabled: boolean;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  async function save(value?: Parameters<typeof change>[1]) {
    setBusy(true);
    setError('');
    try {
      if (value) await change(input, value);
      else await onEdit(input);
    } catch (e) {
      setError(apiErrorMessage(e, t('inputFailed')));
    } finally {
      setBusy(false);
    }
  }
  const steer = input.mode === 'steer';
  return (
    <div className="agent-input-queue__item">
      <ListTree size={16} className="agent-input-queue__icon" aria-hidden />
      <p title={input.content}>
        {input.content || t('inputQueue2')}
        {input.file_ids.length > 0 &&
          ` · ${input.file_ids.length} ${t('inputQueue3')}`}
      </p>
      <div className="agent-input-queue__actions">
        <Tooltip
          title={
            steer
              ? t('inputQueue4')
              : t('inputQueue5')
          }
          trigger={['hover', 'focus']}
          mouseEnterDelay={0.08}
        >
          <span className="agent-input-queue__steer-hint">
            <button
              disabled={disabled || busy || steer}
              className="agent-input-queue__steer"
              onClick={() => void save({ mode: 'steer' })}
            >
              <CornerDownRight size={16} aria-hidden />
              {steer ? t('inputQueue6') : t('inputQueue7')}
            </button>
          </span>
        </Tooltip>
        <Tooltip
          title={t('inputQueue8')}
          trigger={['hover', 'focus']}
          mouseEnterDelay={0.08}
        >
          <button
            disabled={disabled || busy}
            aria-label={t('inputQueue9')}
            onClick={() => void save({ cancel: true })}
          >
            <Trash2 size={16} aria-hidden />
          </button>
        </Tooltip>
        <Dropdown
          trigger={['click']}
          placement="topRight"
          menu={{
            items: [
              {
                key: 'edit',
                label: t('inputQueue10'),
                icon: <Pencil size={14} />,
              },
              ...(steer
                ? [
                    {
                      key: 'queue',
                      label: t('inputQueue11'),
                      icon: <ListEnd size={14} />,
                    },
                  ]
                : []),
              ...(input.status === 'failed'
                ? [
                    {
                      key: 'retry',
                      label: t('inputQueue12'),
                      icon: <RotateCcw size={14} />,
                    },
                  ]
                : []),
            ],
            onClick: ({ key }) => {
              if (key === 'edit') void save();
              else void save({ mode: key === 'queue' ? 'queue' : input.mode });
            },
          }}
        >
          <button
            disabled={disabled || busy}
            aria-label={t('inputQueue13')}
          >
            <Ellipsis size={16} aria-hidden />
          </button>
        </Dropdown>
      </div>
      {(error || input.error_message) && (
        <div className="agent-input-queue__error" role="alert">
          {error || input.error_message}
        </div>
      )}
    </div>
  );
}
