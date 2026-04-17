/**
 * Tests for useConfirmModal hook
 */
import { renderHook, act } from '@testing-library/react';
import { useConfirmModal } from '../useConfirmModal';
import { render, screen, fireEvent } from '@testing-library/react';

describe('useConfirmModal', () => {
  it('should open modal with correct options', async () => {
    const { result } = renderHook(() => useConfirmModal());

    // Initially modal should not be visible
    const { container } = render(<result.current.ConfirmModal />);
    expect(container.firstChild).toBeNull();

    // Open modal
    act(() => {
      result.current.confirm!({
        title: 'Test Title',
        message: 'Test message',
        variant: 'danger',
      });
    });

    // Re-render to show modal
    render(<result.current.ConfirmModal />);

    // Modal should be visible
    expect(screen.getByText('Test Title')).toBeInTheDocument();
    expect(screen.getByText('Test message')).toBeInTheDocument();
    expect(screen.getByText('Confirm')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('should resolve true when confirmed', async () => {
    const { result } = renderHook(() => useConfirmModal());

    let promise: Promise<boolean>;
    act(() => {
      promise = result.current.confirm({
        title: 'Confirm?',
        message: 'Are you sure?',
      });
    });

    render(<result.current.ConfirmModal />);

    // Click confirm
    fireEvent.click(screen.getByText('Confirm'));

    await expect(promise!).resolves.toBe(true);
  });

  it('should resolve false when cancelled', async () => {
    const { result } = renderHook(() => useConfirmModal());

    let promise: Promise<boolean>;
    act(() => {
      promise = result.current.confirm!({
        title: 'Confirm?',
        message: 'Are you sure?',
      });
    });

    render(<result.current.ConfirmModal />);

    // Click cancel
    fireEvent.click(screen.getByText('Cancel'));

    await expect(promise!).resolves.toBe(false);
  });

  it('should call onConfirm callback when confirmed', async () => {
    const onConfirm = jest.fn();
    const { result } = renderHook(() => useConfirmModal());

    act(() => {
      result.current.confirm!({
        title: 'Confirm?',
        message: 'Are you sure?',
        onConfirm,
      });
    });

    render(<result.current.ConfirmModal />);

    fireEvent.click(screen.getByText('Confirm'));

    expect(onConfirm).toHaveBeenCalled();
  });

  it('should call onCancel callback when cancelled', async () => {
    const onCancel = jest.fn();
    const { result } = renderHook(() => useConfirmModal());

    act(() => {
      result.current.confirm!({
        title: 'Confirm?',
        message: 'Are you sure?',
        onCancel,
      });
    });

    render(<result.current.ConfirmModal />);

    fireEvent.click(screen.getByText('Cancel'));

    expect(onCancel).toHaveBeenCalled();
  });

  it('should use custom button text', () => {
    const { result } = renderHook(() => useConfirmModal());

    act(() => {
      result.current.confirm({
        title: 'Confirm?',
        message: 'Are you sure?',
        confirmText: 'Yes, Delete',
        cancelText: 'No, Keep',
      });
    });

    render(<result.current.ConfirmModal />);

    expect(screen.getByText('Yes, Delete')).toBeInTheDocument();
    expect(screen.getByText('No, Keep')).toBeInTheDocument();
  });

  it('should handle async onConfirm', async () => {
    const asyncOnConfirm = jest.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useConfirmModal());

    let promise: Promise<boolean>;
    act(() => {
      promise = result.current.confirm!({
        title: 'Confirm?',
        message: 'Are you sure?',
        onConfirm: asyncOnConfirm,
      });
    });

    render(<result.current.ConfirmModal />);

    fireEvent.click(screen.getByText('Confirm'));

    await expect(promise!).resolves.toBe(true);
    expect(asyncOnConfirm).toHaveBeenCalled();
  });
});
