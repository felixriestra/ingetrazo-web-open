/**
 * The Preferences window: General, Units, Import and Keyboard shortcuts in one place, as on
 * the desktop. Settings apply as they change; everything is kept in this browser.
 */
import {availableLanguages, currentLanguage, setLanguage} from "./i18n";
import {prefs, resetPrefs, setPrefs, UNIT_LENGTHS} from "./prefs";
import type {Preferences} from "./prefs";
import {setThemePreference, themePreference} from "./theme";
import type {ThemePreference} from "./theme";

export type PreferencesTab = "general" | "units" | "import" | "shortcuts";

export interface PreferencesDeps {
  shortcutsPanel: () => {element: HTMLElement; dispose: () => void};
  selectDrag: () => "box" | "orbit";
  setSelectDrag: (value: "box" | "orbit") => void;
  toolbarPx: () => number;
  setToolbarPx: (px: number) => void;
}

let openDialog: HTMLDialogElement | undefined;

function row(label: string, control: HTMLElement, hint = ""): HTMLLabelElement {
  const wrapper = document.createElement("label");
  wrapper.className = "pref-row";
  wrapper.append(Object.assign(document.createElement("span"), {textContent: label}), control);
  if (hint) wrapper.title = hint;
  return wrapper;
}

function select(options: [string, string][], value: string, change: (value: string) => void): HTMLSelectElement {
  const element = document.createElement("select");
  for (const [key, text] of options) element.append(new Option(text, key, false, key === value));
  element.addEventListener("change", () => change(element.value));
  return element;
}

function checkbox(value: boolean, change: (value: boolean) => void): HTMLInputElement {
  const element = Object.assign(document.createElement("input"), {type: "checkbox", checked: value});
  element.addEventListener("change", () => change(element.checked));
  return element;
}

function slider(low: number, high: number, value: number, change: (value: number) => void): HTMLElement {
  const wrap = document.createElement("span");
  wrap.className = "pref-slider";
  const input = Object.assign(document.createElement("input"), {type: "range", min: String(low), max: String(high), step: "0.1", value: String(value)});
  const label = Object.assign(document.createElement("output"), {textContent: `${value.toFixed(1)}×`});
  input.addEventListener("input", () => { label.textContent = `${Number(input.value).toFixed(1)}×`; change(Number(input.value)); });
  wrap.append(input, label);
  return wrap;
}

function numberInput(value: number, low: number, high: number, step: string, change: (value: number) => void): HTMLInputElement {
  const input = Object.assign(document.createElement("input"), {type: "number", value: String(value), min: String(low), max: String(high), step});
  input.addEventListener("change", () => { if (Number.isFinite(input.valueAsNumber)) change(Math.min(high, Math.max(low, input.valueAsNumber))); });
  return input;
}

/** What the server keeps: edits are saved as revisions at once, and Undo steps through them. */
function retentionNote(): HTMLElement {
  const note = Object.assign(document.createElement("p"), {className: "muted",
    textContent: "Every edit is saved at once as a revision, and Undo and Redo step back and forth through them."});
  void fetch("/api/v1/capabilities").then(response => response.json()).then((capabilities: {limits?: {keep_revisions?: number}}) => {
    const keep = capabilities.limits?.keep_revisions ?? 0;
    note.textContent += keep
      ? ` This server keeps the first revision and the last ${keep} of each document, so Undo goes back about ${keep} steps.`
      : " This server keeps every revision, so Undo has no limit.";
  }).catch(() => undefined);
  return note;
}

export function openPreferences(deps: PreferencesDeps, tab: PreferencesTab = "general"): void {
  if (openDialog) { openDialog.close(); }
  const dialog = document.createElement("dialog");
  dialog.className = "shortcut-dialog preferences";
  openDialog = dialog;
  let dispose: (() => void) | undefined;

  const heading = Object.assign(document.createElement("h2"), {textContent: "Preferences"});
  const tabs = document.createElement("div");
  tabs.className = "pref-tabs";
  tabs.setAttribute("role", "tablist");
  const page = document.createElement("div");
  page.className = "pref-page";

  const pages: Record<PreferencesTab, [string, () => HTMLElement]> = {
    general: ["General", () => {
      const box = document.createElement("div");
      const p = prefs();
      box.append(
        row("Theme", select([["dark", "Dark"], ["light", "Light"], ["system", "Follow the system"]], themePreference(),
          value => setThemePreference(value as ThemePreference))),
        row("Language", select(availableLanguages().map(item => [item.code, item.name] as [string, string]), currentLanguage(),
          value => void setLanguage(value))),
        row("Select tool, left-drag", select([["box", "Draws a selection box"], ["orbit", "Orbits the view"]], deps.selectDrag(),
          value => deps.setSelectDrag(value as "box" | "orbit"))),
        row("Toolbar icons", select([28, 32, 40, 48].map(px => [String(px), `${px} px`] as [string, string]), String(deps.toolbarPx()),
          value => deps.setToolbarPx(Number(value)))),
        Object.assign(document.createElement("h3"), {textContent: "Saving and history"}),
        row("Auto-save presentation changes", checkbox(p.autoSavePresentation, value => setPrefs({autoSavePresentation: value})),
          "Layer and object visibility changes wait for Save presentation changes; this saves them by itself"),
        row("…after this many quiet seconds", numberInput(p.autoSaveSeconds, 5, 600, "1", value => setPrefs({autoSaveSeconds: Math.round(value)}))),
        retentionNote(),
        Object.assign(document.createElement("h3"), {textContent: "Mouse and touch"}),
        row("Orbit speed", slider(0.2, 3, p.orbitSpeed, value => setPrefs({orbitSpeed: value}))),
        row("Zoom speed", slider(0.2, 3, p.zoomSpeed, value => setPrefs({zoomSpeed: value}))),
        row("Invert mouse wheel zoom", checkbox(p.invertZoom, value => setPrefs({invertZoom: value}))),
        row("Invert vertical orbit", checkbox(p.invertOrbitVertical, value => setPrefs({invertOrbitVertical: value}))));
      return box;
    }],
    units: ["Units", () => {
      const box = document.createElement("div");
      const p = prefs();
      const fixed = (): boolean => prefs().unitsMode === "fixed";
      const length = select(UNIT_LENGTHS.map(unit => [unit, unit] as [string, string]), p.unitLength, value => setPrefs({unitLength: value as Preferences["unitLength"]}));
      const precision = numberInput(p.unitPrecision, 0, 6, "1", value => setPrefs({unitPrecision: Math.round(value)}));
      const sync = () => { length.disabled = precision.disabled = !fixed(); };
      const mode = select([["document", "Use each document's own units"], ["fixed", "Always use the units below"]], p.unitsMode,
        value => { setPrefs({unitsMode: value as Preferences["unitsMode"]}); sync(); });
      sync();
      box.append(row("Show lengths in", mode), row("Length unit", length), row("Decimal places", precision),
        Object.assign(document.createElement("p"), {className: "muted", textContent:
          "This sets how lengths are shown and typed in the Measurements box and the forms. The document keeps storing metres."}));
      return box;
    }],
    import: ["Import", () => {
      const box = document.createElement("div");
      const p = prefs();
      box.append(
        row("Ask for the scale each time", checkbox(p.importAsk, value => setPrefs({importAsk: value}))),
        row("OBJ files", numberInput(p.importScale.obj, 1e-6, 1e6, "any", value => setPrefs({importScale: {...prefs().importScale, obj: value}}))),
        row("STL files", numberInput(p.importScale.stl, 1e-6, 1e6, "any", value => setPrefs({importScale: {...prefs().importScale, stl: value}}))),
        row("DXF files", numberInput(p.importScale.dxf, 1e-6, 1e6, "any", value => setPrefs({importScale: {...prefs().importScale, dxf: value}}))),
        Object.assign(document.createElement("p"), {className: "muted", textContent:
          "The factor that turns the file's numbers into metres: 1 if the file is in metres, 0.001 for millimetres, 0.01 for centimetres, 0.3048 for feet."}));
      return box;
    }],
    shortcuts: ["Keyboard shortcuts", () => {
      const made = deps.shortcutsPanel();
      dispose = made.dispose;
      return made.element;
    }],
  };

  function show(which: PreferencesTab): void {
    dispose?.();
    dispose = undefined;
    page.replaceChildren(pages[which][1]());
    for (const button of tabs.querySelectorAll<HTMLButtonElement>("button")) {
      const active = button.dataset.tab === which;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    }
  }

  for (const key of Object.keys(pages) as PreferencesTab[]) {
    const button = Object.assign(document.createElement("button"), {type: "button", textContent: pages[key][0], className: "pref-tab"});
    button.dataset.tab = key;
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => show(key));
    tabs.append(button);
  }

  const footer = document.createElement("div");
  footer.className = "dialog-buttons";
  const reset = Object.assign(document.createElement("button"), {type: "button", textContent: "Reset to defaults", title: "Resets the General, Units and Import settings (not theme, language, shortcuts or toolbar layout)"});
  reset.addEventListener("click", () => { resetPrefs(); const active = tabs.querySelector<HTMLButtonElement>(".active")?.dataset.tab as PreferencesTab; show(active ?? "general"); });
  const close = Object.assign(document.createElement("button"), {type: "button", textContent: "Close"});
  close.addEventListener("click", () => dialog.close());
  footer.append(reset, close);

  dialog.addEventListener("close", () => { dispose?.(); dialog.remove(); if (openDialog === dialog) openDialog = undefined; });
  dialog.append(heading, tabs, page, footer);
  document.body.append(dialog);
  show(tab);
  dialog.showModal();
}
