import React from 'react';

const ThemeToggle: React.FC = () => (
  <button type="button" title="Toggle theme" className="theme-toggle p-2 rounded text-slate-400 hover:text-white">
    🌙
  </button>
);

const MemoizedThemeToggle = React.memo(ThemeToggle);
MemoizedThemeToggle.displayName = 'ThemeToggle';
export default MemoizedThemeToggle;
