/* eslint-disable react-refresh/only-export-components */
import React from "react";

type Theme = "light" | "dark";
const ThemeContext = React.createContext<{
  theme: Theme;
  toggleTheme: () => void;
  setPreference: (t: Theme) => void;
}>({ theme: "dark", toggleTheme: () => undefined, setPreference: () => undefined });

export const ThemeProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [theme, setTheme] = React.useState<Theme>(() => {
    return (localStorage.getItem("merid-theme") as Theme) || "dark";
  });

  React.useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    localStorage.setItem("merid-theme", theme);
  }, [theme]);

  return (
    <ThemeContext.Provider
      value={{ theme, toggleTheme: () => setTheme(t => (t === "dark" ? "light" : "dark")), setPreference: setTheme }}
    >
      <div className={`min-h-screen ${theme === 'dark' ? 'bg-slate-950 text-slate-100' : 'bg-white text-slate-900'}`}>
        {children}
      </div>
    </ThemeContext.Provider>
  );
};

export const useTheme = () => React.useContext(ThemeContext);
