import { useState, useCallback, useEffect, useRef } from 'react';
import React from 'react';

export interface ConfirmModalOptions {
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info';
  onConfirm?: () => void | Promise<void>;
  onCancel?: () => void;
}

interface ConfirmModalState extends ConfirmModalOptions {
  isOpen: boolean;
}

export interface UseConfirmModalReturn {
  confirm: (options: ConfirmModalOptions) => Promise<boolean>;
  ConfirmModal: () => React.ReactElement | null;
}

/**
 * Hook for managing accessible confirmation modals as a replacement for window.confirm()
 * 
 * Features:
 * - ARIA attributes for screen readers
 * - Focus management (traps focus, returns focus)
 * - ARIA live regions for dynamic content
 * - Keyboard navigation (Escape to cancel, Enter to confirm)
 * 
 * Usage:
 * const { confirm, ConfirmModal } = useConfirmModal();
 * 
 * // In your component:
 * <ConfirmModal />
 * 
 * // To trigger:
 * await confirm({
 *   title: 'Delete Item?',
 *   message: 'This action cannot be undone.',
 *   variant: 'danger',
 * });
 */
export function useConfirmModal(): UseConfirmModalReturn {
  const [state, setState] = useState<ConfirmModalState>({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    variant: 'info',
  });

  const [resolveRef, setResolveRef] = useState<{
    resolve: (value: boolean) => void;
  } | null>(null);

  const modalRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const confirm = useCallback((options: ConfirmModalOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setResolveRef({ resolve });
      setState({
        ...options,
        confirmText: options.confirmText ?? 'Confirm',
        cancelText: options.cancelText ?? 'Cancel',
        variant: options.variant ?? 'info',
        isOpen: true,
      });
    });
  }, []);

  const handleConfirm = useCallback(async () => {
    if (state.onConfirm) {
      await state.onConfirm();
    }
    setState((prev) => ({ ...prev, isOpen: false }));
    resolveRef?.resolve(true);
    setResolveRef(null);
  }, [state, resolveRef]);

  const handleCancel = useCallback(() => {
    if (state.onCancel) {
      state.onCancel();
    }
    setState((prev) => ({ ...prev, isOpen: false }));
    resolveRef?.resolve(false);
    setResolveRef(null);
  }, [state, resolveRef]);

  // Focus management and keyboard handling
  useEffect(() => {
    if (state.isOpen) {
      // Store current focus
      previousFocusRef.current = document.activeElement as HTMLElement;
      
      // Focus the modal
      setTimeout(() => {
        if (modalRef.current) {
          modalRef.current.focus();
        }
      }, 100);

      // Handle keyboard events
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          handleCancel();
        } else if (event.key === 'Enter') {
          handleConfirm();
        }
      };

      document.addEventListener('keydown', handleKeyDown);

      // Prevent body scroll
      document.body.style.overflow = 'hidden';

      return () => {
        document.removeEventListener('keydown', handleKeyDown);
        document.body.style.overflow = '';

        // Restore focus
        if (previousFocusRef.current && typeof previousFocusRef.current.focus === 'function') {
          previousFocusRef.current.focus();
        }
      };
    }
  }, [state.isOpen, handleCancel, handleConfirm]);

  const ConfirmModalComponent = useCallback(() => {
    if (!state.isOpen) return null;

    const variantStyles = {
      danger: 'bg-red-600 hover:bg-red-500 focus:ring-red-500',
      warning: 'bg-amber-600 hover:bg-amber-500 focus:ring-amber-500',
      info: 'bg-blue-600 hover:bg-blue-500 focus:ring-blue-500',
    };

    return React.createElement(
      'div',
      {
        className: 'fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm',
        'aria-hidden': 'false',
        role: 'dialog',
        'aria-modal': 'true',
        'aria-labelledby': 'confirm-modal-title',
        'aria-describedby': 'confirm-modal-message',
      },
      React.createElement(
        'div',
        {
          ref: modalRef,
          className: 'bg-slate-800 rounded-xl border border-slate-700 p-6 max-w-md w-full mx-4 shadow-2xl focus:outline-none',
          tabIndex: -1,
          role: 'document',
        },
        React.createElement(
          'header',
          {},
          React.createElement(
            'h3',
            {
              id: 'confirm-modal-title',
              className: 'text-lg font-semibold text-white mb-3',
            },
            state.title
          )
        ),
        React.createElement(
          'p',
          {
            id: 'confirm-modal-message',
            className: 'text-gray-300 mb-6 whitespace-pre-wrap',
            'aria-live': 'polite',
          },
          state.message
        ),
        React.createElement(
          'div',
          { className: 'flex gap-3 justify-end' },
          React.createElement(
            'button',
            {
              onClick: handleCancel,
              className: 'px-4 py-2 rounded-lg bg-slate-700 text-gray-300 hover:bg-slate-600 focus:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-500 transition-colors',
              'aria-label': state.cancelText,
            },
            state.cancelText
          ),
          React.createElement(
            'button',
            {
              onClick: handleConfirm,
              className: `px-4 py-2 rounded-lg text-white focus:outline-none focus:ring-2 transition-colors ${variantStyles[state.variant!]}`,
              'aria-label': state.confirmText,
            },
            state.confirmText
          )
        )
      )
    );
  }, [state, handleConfirm, handleCancel]);

  return {
    confirm,
    ConfirmModal: ConfirmModalComponent,
  };
}
