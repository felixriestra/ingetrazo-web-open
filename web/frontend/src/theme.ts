/**
 * Light / dark chrome that follows the system or a fixed choice (Preferences).
 * Only the interface changes; the 3D viewport keeps the model's display style.
 */
export type ThemePreference = "system" | "dark" | "light";

const KEY = "ingetrazo.theme";
const listeners: (() => void)[] = [];
const system = window.matchMedia("(prefers-color-scheme: light)");

function read(): ThemePreference {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "dark";
  } catch { return "dark"; }
}

export function themePreference(): ThemePreference { return read(); }

export function effectiveTheme(): "light" | "dark" {
  const choice = read();
  return choice === "system" ? (system.matches ? "light" : "dark") : choice;
}

export function applyTheme(): void {
  document.documentElement.dataset.theme = effectiveTheme();
  for (const listener of listeners) listener();
}

export function setThemePreference(choice: ThemePreference): void {
  try { localStorage.setItem(KEY, choice); } catch { /* private mode: apply for this session only */ }
  applyTheme();
}

export function onThemeChange(listener: () => void): void { listeners.push(listener); }

system.addEventListener("change", () => { if (read() === "system") applyTheme(); });
applyTheme();
