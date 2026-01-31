import { useTheme } from '../theme';
import { Moon, Sun } from 'lucide-react';

export default function ThemeToggle() {
  const { theme, toggle } = useTheme();

  return (
    <button
      onClick={toggle}
      className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-xs hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900"
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
    </button>
  );
}
