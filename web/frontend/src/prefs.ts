/**
 * Preferences kept in this browser.
 *
 * One typed object with defaults, saved as JSON, with change listeners so the viewer, the
 * Measurements box and the import dialog follow the settings as they change. Theme,
 * language, shortcuts and the toolbar layout keep their own storage (see theme.ts,
 * i18n.ts, shortcuts.ts, toolbars.ts); the Preferences window gathers them all.
 */
export interface Preferences {
  /** Orbit speed and zoom speed multipliers (1 = the default feel). */
  orbitSpeed: number;
  zoomSpeed: number;
  invertZoom: boolean;
  invertOrbitVertical: boolean;
  /** "document" shows each document's own units; "fixed" always uses ``unitLength``. */
  unitsMode: "document" | "fixed";
  unitLength: "m" | "cm" | "mm" | "ft" | "in";
  unitPrecision: number;
  /** Scale applied to OBJ, STL and DXF imports (1 = the file is in metres), and whether to ask each time. */
  importScale: {obj: number; stl: number; dxf: number};
  importAsk: boolean;
  /** Save layer and object visibility changes by themselves after this many quiet seconds. */
  autoSavePresentation: boolean;
  autoSaveSeconds: number;
}

const KEY = "ingetrazo.prefs";
export const DEFAULTS: Preferences = {
  orbitSpeed: 1, zoomSpeed: 1, invertZoom: false, invertOrbitVertical: false,
  unitsMode: "document", unitLength: "m", unitPrecision: 2,
  importScale: {obj: 1, stl: 1, dxf: 1}, importAsk: true,
  autoSavePresentation: false, autoSaveSeconds: 30,
};
export const UNIT_LENGTHS: Preferences["unitLength"][] = ["m", "cm", "mm", "ft", "in"];

const listeners: (() => void)[] = [];

const number = (value: unknown, low: number, high: number, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? Math.min(high, Math.max(low, value)) : fallback;

function load(): Preferences {
  let raw: Record<string, unknown> = {};
  try { raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Record<string, unknown>; } catch { /* defaults */ }
  const scale = (raw.importScale ?? {}) as Record<string, unknown>;
  return {
    orbitSpeed: number(raw.orbitSpeed, 0.2, 4, DEFAULTS.orbitSpeed),
    zoomSpeed: number(raw.zoomSpeed, 0.2, 4, DEFAULTS.zoomSpeed),
    invertZoom: raw.invertZoom === true,
    invertOrbitVertical: raw.invertOrbitVertical === true,
    unitsMode: raw.unitsMode === "fixed" ? "fixed" : "document",
    unitLength: UNIT_LENGTHS.includes(raw.unitLength as Preferences["unitLength"]) ? raw.unitLength as Preferences["unitLength"] : "m",
    unitPrecision: Math.round(number(raw.unitPrecision, 0, 6, DEFAULTS.unitPrecision)),
    importScale: {
      obj: number(scale.obj, 1e-6, 1e6, 1), stl: number(scale.stl, 1e-6, 1e6, 1), dxf: number(scale.dxf, 1e-6, 1e6, 1)},
    importAsk: raw.importAsk !== false,
    autoSavePresentation: raw.autoSavePresentation === true,
    autoSaveSeconds: Math.round(number(raw.autoSaveSeconds, 5, 600, DEFAULTS.autoSaveSeconds)),
  };
}

let current: Preferences = load();      // after the helpers it uses (they are consts)

export const prefs = (): Preferences => current;

export function setPrefs(patch: Partial<Preferences>): void {
  current = {...current, ...patch, importScale: {...current.importScale, ...(patch.importScale ?? {})}};
  try { localStorage.setItem(KEY, JSON.stringify(current)); } catch { /* session only */ }
  for (const listener of listeners) listener();
}

export const resetPrefs = (): void => setPrefs({...DEFAULTS, importScale: {...DEFAULTS.importScale}});
export const onPrefsChange = (listener: () => void): void => { listeners.push(listener); };
