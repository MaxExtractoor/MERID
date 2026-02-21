import { useState, useRef, useEffect } from 'react';
import { HelpCircle, X } from 'lucide-react';

interface HelpPopoverProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Small "?" icon that opens a popover with operator-facing help text.
 * Closes on click-outside or pressing the X button.
 */
export function HelpPopover({ title, children, className = '' }: HelpPopoverProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div className={`relative inline-flex ${className}`} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="p-0.5 rounded-full text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
        title={`Help: ${title}`}
        aria-label={`Help: ${title}`}
      >
        <HelpCircle className="w-3.5 h-3.5" />
      </button>

      {open && (
        <div className="absolute z-50 top-full mt-1 right-0 w-72 bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 text-xs text-slate-300 space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-200">{title}</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-slate-300"
              aria-label="Close help"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <div className="leading-relaxed">{children}</div>
        </div>
      )}
    </div>
  );
}
