/**
 * Customisable keyboard shortcuts.
 *
 * The desktop's default keys come from the exported manifest; the viewer's own
 * choices are kept in this browser (localStorage) as overrides, can be exported to a
 * JSON file and imported again, and are edited from Help > Keyboard shortcuts.
 */
import {notice} from "./dialogs";

export interface ShortcutTool {name: string; shortcut: string; shortcut_alt: string}
type Pair = [string, string];

const STORAGE = "ingetrazo.shortcuts";

/** The lowercase combo a key press stands for: "ctrl+shift+o", "space", "l". */
export function comboOf(event: KeyboardEvent): string | undefined {
  if (["Shift", "Control", "Alt", "Meta", "Dead"].includes(event.key)) return undefined;
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push("ctrl");
  if (event.altKey) parts.push("alt");
  if (event.shiftKey) parts.push("shift");
  parts.push(event.key === " " ? "space" : event.key.toLowerCase());
  return parts.join("+");
}

const pretty = (combo: string) => combo.split("+").map(part => part.length === 1 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)).join("+");

export interface Shortcuts {
  /** The two shortcuts of a tool, as shown (empty string = none). */
  get: (key: string) => Pair;
  /** The tool a combo triggers, if any. */
  lookup: (combo: string) => string | undefined;
  /** "L / Ctrl+L" for menus and tooltips. */
  label: (key: string) => string;
  onChange: (listener: () => void) => void;
  edit: () => void;
  /** The editor as an element, for embedding. */
  panel: () => {element: HTMLElement; dispose: () => void};
}

export function createShortcuts(tools: Record<string, ShortcutTool>, fixed: Set<string>): Shortcuts {
  let overrides: Record<string, Pair> = {};
  try {
    const raw = localStorage.getItem(STORAGE);
    if (raw) overrides = sanitize(JSON.parse(raw));
  } catch { /* defaults */ }
  const listeners: (() => void)[] = [];

  function sanitize(value: unknown): Record<string, Pair> {
    const out: Record<string, Pair> = {};
    if (!value || typeof value !== "object") return out;
    for (const [key, pair] of Object.entries(value as Record<string, unknown>)) {
      if (!(key in tools) || !Array.isArray(pair)) continue;
      const clean = [0, 1].map(index => typeof pair[index] === "string" ? String(pair[index]).toLowerCase().slice(0, 40) : "") as Pair;
      out[key] = clean;
    }
    return out;
  }
  const defaults = (key: string): Pair => [tools[key].shortcut.toLowerCase(), tools[key].shortcut_alt.toLowerCase()];
  const get = (key: string): Pair => overrides[key] ?? defaults(key);
  const save = () => {
    try { localStorage.setItem(STORAGE, JSON.stringify(overrides)); } catch { /* session only */ }
    for (const listener of listeners) listener();
  };

  const lookup = (combo: string): string | undefined => {
    for (const key of Object.keys(tools)) {
      if (fixed.has(key)) continue;
      if (get(key).includes(combo)) return key;
    }
    return undefined;
  };

  function assign(key: string, slot: 0 | 1, combo: string): string | undefined {
    let moved: string | undefined;
    if (combo) {
      for (const other of Object.keys(tools)) {
        if (fixed.has(other)) continue;
        const pair = [...get(other)] as Pair;
        [0, 1].forEach(index => {
          if (pair[index] === combo && !(other === key && index === slot)) {
            pair[index] = "";
            overrides[other] = pair;
            if (other !== key) moved = tools[other].name;
          }
        });
      }
    }
    const pair = [...get(key)] as Pair;
    pair[slot] = combo;
    overrides[key] = pair;
    return moved;
  }

  /** The editor as an element (for the Preferences window); ``dispose`` stops a key capture in progress. */
  function panel(onClose?: () => void): {element: HTMLElement; dispose: () => void} {
    const element = document.createElement("div");
    element.className = "shortcut-panel";
    const heading = Object.assign(document.createElement("h2"), {textContent: "Keyboard shortcuts"});
    const help = Object.assign(document.createElement("p"), {
      className: "muted", textContent: "Click a key box, then press the new shortcut. Backspace clears it, Esc cancels. A key already used by another tool moves to this one."});
    const message = Object.assign(document.createElement("p"), {className: "muted"});
    const table = document.createElement("table");
    table.className = "shortcut-table";
    let capturing: HTMLButtonElement | undefined;
    let stop: (() => void) | undefined;

    function render(): void {
      table.replaceChildren();
      for (const [key, tool] of Object.entries(tools)) {
        if (fixed.has(key)) continue;
        const row = table.insertRow();
        row.insertCell().textContent = tool.name;
        ([0, 1] as const).forEach(slot => {
          const button = Object.assign(document.createElement("button"), {type: "button", className: "key-box",
            textContent: get(key)[slot] ? pretty(get(key)[slot]) : "—", title: slot ? "Alternative shortcut" : "Shortcut"});
          button.addEventListener("click", () => {
            stop?.();
            capturing = button;
            button.textContent = "Press keys…";
            button.classList.add("capturing");
            const listener = (event: KeyboardEvent) => {
              if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); finish(); render(); return; }
              const combo = event.key === "Backspace" || event.key === "Delete" ? "" : comboOf(event);
              if (combo === undefined) return;
              event.preventDefault();
              event.stopPropagation();
              const moved = assign(key, slot, combo);
              save();
              finish();
              message.textContent = moved ? `${pretty(combo)} moved here from ${moved}.` : "";
              render();
            };
            const finish = () => { document.removeEventListener("keydown", listener, true); capturing = undefined; stop = undefined; };
            stop = finish;
            document.addEventListener("keydown", listener, true);
          });
          row.insertCell().append(button);
        });
        const reset = Object.assign(document.createElement("button"), {type: "button", textContent: "Reset", className: "layer-button", hidden: !(key in overrides)});
        reset.addEventListener("click", () => { delete overrides[key]; save(); render(); });
        row.insertCell().append(reset);
      }
    }

    const footer = document.createElement("div");
    footer.className = "dialog-buttons";
    const button = (label: string, run: () => void) => {
      const element = Object.assign(document.createElement("button"), {type: "button", textContent: label});
      element.addEventListener("click", run);
      return element;
    };
    const exportButton = button("Export…", () => {
      const blob = new Blob([JSON.stringify({ingetrazo_shortcuts: 1, shortcuts: overrides}, null, 2)], {type: "application/json"});
      const link = Object.assign(document.createElement("a"), {href: URL.createObjectURL(blob), download: "ingetrazo-shortcuts.json"});
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });
    const importButton = button("Import…", () => {
      const picker = Object.assign(document.createElement("input"), {type: "file", accept: "application/json,.json"});
      picker.addEventListener("change", async () => {
        const file = picker.files?.[0];
        if (!file) return;
        try {
          const parsed = JSON.parse(await file.text()) as {shortcuts?: unknown};
          const imported = sanitize(parsed.shortcuts);
          if (!Object.keys(imported).length) throw new Error("no shortcuts in the file");
          overrides = imported;
          save();
          render();
          message.textContent = `Imported ${Object.keys(imported).length} shortcuts.`;
        } catch (error) {
          notice("Import shortcuts", `That file is not a shortcuts export: ${error instanceof Error ? error.message : String(error)}`);
        }
      });
      picker.click();
    });
    const resetAll = button("Reset all", () => { overrides = {}; save(); render(); message.textContent = "Back to the desktop's shortcuts."; });
    footer.append(exportButton, importButton, resetAll);
    if (onClose) footer.append(button("Close", onClose));
    element.append(onClose ? heading : document.createElement("span"), help, message, table, footer);
    render();
    return {element, dispose: () => { stop?.(); void capturing; }};
  }

  function edit(): void {
    const dialog = document.createElement("dialog");
    dialog.className = "shortcut-dialog shortcut-editor";
    const {element, dispose} = panel(() => dialog.close());
    dialog.addEventListener("close", () => { dispose(); dialog.remove(); });
    dialog.append(element);
    document.body.append(dialog);
    dialog.showModal();
  }

  return {
    get, lookup, edit, panel: () => panel(),
    label: key => get(key).filter(Boolean).map(pretty).join(" / "),
    onChange: listener => { listeners.push(listener); },
  };
}
