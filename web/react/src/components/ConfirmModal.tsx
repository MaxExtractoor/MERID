import React from 'react';
import './ConfirmModal.css';

export interface ChecklistItem {
  id: string;
  label: string;
}

export interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  confirmVariant?: 'primary' | 'danger' | 'warning';
  confirmDisabled?: boolean;
  checklistItems?: ChecklistItem[];
  onChecklistChange?: (checkedIds: string[]) => void;
  onConfirm: () => void;
  onCancel: () => void;
  'aria-label'?: string;
  children?: React.ReactNode;
}

function ConfirmModalComponent({
  isOpen,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  confirmVariant = 'primary',
  confirmDisabled = false,
  checklistItems = [],
  onChecklistChange,
  onConfirm,
  onCancel,
  'aria-label': ariaLabel,
  children,
}: ConfirmModalProps) {
  const [checkedIds, setCheckedIds] = React.useState<string[]>([]);

  React.useEffect(() => {
    if (isOpen) {
      setCheckedIds([]);
    }
  }, [isOpen]);

  // Escape key dismisses the modal — bound to window so no JSX keyboard
  // listener is needed on the non-interactive overlay element.
  React.useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  const handleChecklistChange = (itemId: string, checked: boolean) => {
    const newChecked = checked
      ? [...checkedIds, itemId]
      : checkedIds.filter(id => id !== itemId);
    setCheckedIds(newChecked);
    onChecklistChange?.(newChecked);
  };

  const isChecklistComplete = checklistItems.length === 0 || checkedIds.length === checklistItems.length;
  const effectiveConfirmDisabled = confirmDisabled || !isChecklistComplete;

  const handleOverlayClick = (e: React.MouseEvent) => {
    // Only dismiss when the click lands on the overlay itself, not the dialog content.
    if (e.target === e.currentTarget) {
      onCancel();
    }
  };

  return (
    <div
      className="confirm-modal-overlay"
      onClick={handleOverlayClick}
      role="presentation"
    >
      <div
        className="confirm-modal-content"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel || title}
      >
        <h3 className="confirm-modal-title">{title}</h3>
        <p className="confirm-modal-message">{message}</p>
        {checklistItems.length > 0 && (
          <div className="confirm-modal-checklist mb-6 space-y-2">
            {checklistItems.map(item => (
              <label key={item.id} className="flex items-start gap-2 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={checkedIds.includes(item.id)}
                  onChange={e => handleChecklistChange(item.id, e.target.checked)}
                  className="mt-0.5 rounded border-gray-600 bg-gray-800 text-orange-500 focus:ring-orange-500 focus:ring-offset-gray-900"
                />
                <span>{item.label}</span>
              </label>
            ))}
          </div>
        )}
        {children}
        <div className="confirm-modal-actions">
          <button
            type="button"
            className="confirm-modal-cancel"
            onClick={onCancel}
            aria-label={cancelText}
          >
            {cancelText}
          </button>
          <button
            type="button"
            className={`confirm-modal-confirm confirm-modal-confirm--${confirmVariant}`}
            disabled={effectiveConfirmDisabled}
            onClick={onConfirm}
            aria-label={confirmText}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

export const ConfirmModal = React.memo(ConfirmModalComponent);
