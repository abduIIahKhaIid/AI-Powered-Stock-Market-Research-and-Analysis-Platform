import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { loadSettings, saveSettings, type Settings, SettingsContext } from "./context";

function systemDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

export default function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [osDark, setOsDark] = useState(systemDark);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setOsDark(query.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  const resolvedTheme = settings.theme === "system" ? (osDark ? "dark" : "light") : settings.theme;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", resolvedTheme === "dark");
  }, [resolvedTheme]);

  const update = useCallback((change: Partial<Settings>) => {
    setSettings((current) => {
      const next = { ...current, ...change };
      saveSettings(next);
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({ ...settings, resolvedTheme, update }) as const,
    [settings, resolvedTheme, update],
  );
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}
