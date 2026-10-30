/* eslint-disable react-refresh/only-export-components */
import React from "react";

type Theme = "light" | "dark";
const ThemeContext = React.createContext<{
  theme: Theme;
  toggleTheme: () => void;
  setPreference: (t: Theme) => void;
}>({ theme: "dark", toggleTheme: () => undefined, setPreference: () => undefined });

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // The console is dark-only: every component hardcodes slate-dark colors, so
  // honoring a persisted 'light' pref rendered an unreadable hybrid. Force
  // dark and clear any stale light preference.
  const theme: Theme = 'dark';
  const setPreference = React.useCallback(() => undefined, []);
  const toggleTheme = React.useCallback(() => undefined, []);

  React.useEffect(() => {
    document.documentElement.classList.add('dark');
    localStorage.removeItem('merid-theme');
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setPreference }}>
      <div className="min-h-screen bg-slate-950 text-slate-100">
        {children}
      </div>
    </ThemeContext.Provider>
  );
};

export const useTheme = () => React.useContext(ThemeContext);
