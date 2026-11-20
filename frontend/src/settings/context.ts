/** Display settings kept in this browser: theme, how much of the reasoning to show, motion. */
import { createContext, useContext } from "react";
import { prefersReducedMotion } from "../lib/utils";

export type Theme = "light" | "dark" | "system";

/**
 * How much of the assistant's work to show, like Chainlit's `cot` setting:
 * "full" shows the model's thinking and every tool step, "tool_call" only the tool steps,
 * "hidden" only a one-line status while it works.
 */
export type ChainOfThought = "full" | "tool_call" | "hidden";

export interface Settings {
  theme: Theme;
  chainOfThought: ChainOfThought;
  animations: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: "system",
  chainOfThought: "full",
  animations: true,
};

export const SETTINGS_KEY = "stock-research.settings";

export function loadSettings(): Settings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const saved = JSON.parse(raw) as Partial<Settings>;
    return {
      theme: ["light", "dark", "system"].includes(saved.theme as string)
        ? (saved.theme as Theme)
        : DEFAULT_SETTINGS.theme,
      chainOfThought: ["full", "tool_call", "hidden"].includes(saved.chainOfThought as string)
        ? (saved.chainOfThought as ChainOfThought)
        : DEFAULT_SETTINGS.chainOfThought,
      animations:
        typeof saved.animations === "boolean" ? saved.animations : DEFAULT_SETTINGS.animations,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: Settings): void {
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Storage blocked: the settings still apply for this visit.
  }
}

export interface SettingsValue extends Settings {
  /** "light" or "dark" after resolving "system". */
  resolvedTheme: "light" | "dark";
  update: (change: Partial<Settings>) => void;
}

export const SettingsContext = createContext<SettingsValue>({
  ...DEFAULT_SETTINGS,
  resolvedTheme: "light",
  update: () => {},
});

export function useSettings(): SettingsValue {
  return useContext(SettingsContext);
}

/** Whether charts and panels should animate: the setting, unless the OS asks for less motion. */
export function useAnimate(): boolean {
  const { animations } = useSettings();
  return animations && !prefersReducedMotion();
}
