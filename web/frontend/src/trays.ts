/**
 * Right-hand side panel: the desktop's stack of collapsible sections.
 *
 * Each section is a titled header with an arrow; clicking the header folds or
 * unfolds it, and whether it is open is remembered. The panels keep their
 * elements and ids; this only moves them into fold sections, so the code that
 * fills them is unchanged.
 */
interface SectionDef {
  id: string;
  title: string;
  /** Elements to move into the section, by selector (the first match of each). */
  parts: string[];
  open: boolean;
}

// The desktop's order: Entity info, Layers, Scenes, Materials, Components, then the
// panels that have their own docks there (Styles, Location, Sheets ...).
const SECTIONS: SectionDef[] = [
  {id: "document", title: "Document", parts: ["#document-panel", "#create-tools"], open: true},
  {id: "entity", title: "Entity info", parts: ["#selection-panel", "#measurement-panel"], open: true},
  {id: "layers", title: "Layers", parts: ["#layers-panel"], open: true},
  {id: "scenes", title: "Scenes", parts: ["#views-panel"], open: false},
  {id: "sections", title: "Section planes", parts: ["#sections-panel"], open: false},
  {id: "materials", title: "Materials", parts: ["#materials-panel"], open: false},
  {id: "components", title: "Components", parts: ["#components-panel"], open: true},
  {id: "parts", title: "Parts", parts: ["#parts-panel"], open: false},
  {id: "objects", title: "Objects", parts: ["#outline-panel"], open: false},
  {id: "bim", title: "BIM quantities", parts: ["#bim-panel"], open: false},
  {id: "styles", title: "Styles and sun", parts: ["#display-panel"], open: false},
  {id: "location", title: "Location", parts: ["#geospatial-panel"], open: false},
  {id: "sheets", title: "Sheets and PDF", parts: ["#sheets-panel"], open: false},
  {id: "recent", title: "Recent documents", parts: [".library"], open: true},
];

export interface Trays {
  /** Unfold a section and scroll it into view. */
  show: (id: string) => void;
  /** Add a row of action buttons at the top of a section. */
  addActions: (id: string, actions: {label: string; run: () => void}[]) => void;
}

const storageKey = (id: string) => `ingetrazo.fold.${id}`;

function remembered(id: string, fallback: boolean): boolean {
  try {
    const value = localStorage.getItem(storageKey(id));
    return value === null ? fallback : value === "1";
  } catch { return fallback; }
}

export function mountTrays(): Trays {
  const aside = document.querySelector<HTMLElement>("aside")!;

  // The loose "Document" controls become one panel; the Layers section had no id.
  const documentPanel = document.createElement("section");
  documentPanel.id = "document-panel";
  documentPanel.className = "inspector";
  for (const selector of ["h2:not(#tool-panel h2)", "#status", "#cancel-operation", "#save",
    "#save-presentation-revision", "#history-actions", "#restore-revision", "#summary"]) {
    const node = aside.querySelector<HTMLElement>(selector);
    if (node && node.parentElement === aside) documentPanel.append(node);
  }
  aside.append(documentPanel);
  for (const heading of aside.querySelectorAll<HTMLElement>("section.inspector > h2")) {
    if (heading.textContent === "Layers") heading.parentElement!.id = "layers-panel";
  }

  const stack = document.createElement("div");
  stack.className = "fold-stack";
  const folds = new Map<string, {section: HTMLElement; header: HTMLButtonElement; body: HTMLElement}>();

  for (const def of SECTIONS) {
    const section = document.createElement("section");
    section.className = "fold";
    section.id = `fold-${def.id}`;
    const header = document.createElement("button");
    header.type = "button";
    header.className = "fold-header";
    header.setAttribute("aria-controls", `fold-body-${def.id}`);
    const arrow = document.createElement("span");
    arrow.className = "fold-arrow";
    arrow.setAttribute("aria-hidden", "true");
    const title = document.createElement("span");
    title.textContent = def.title;
    header.append(arrow, title);
    const body = document.createElement("div");
    body.className = "fold-body";
    body.id = `fold-body-${def.id}`;
    for (const selector of def.parts) {
      const node = aside.querySelector<HTMLElement>(selector);
      if (node) body.append(node);
    }
    const note = document.createElement("p");
    note.className = "muted fold-empty";
    note.textContent = "Nothing to show for this document yet.";
    body.append(note);
    header.addEventListener("click", () => setOpen(def.id, body.hidden));
    section.append(header, body);
    stack.append(section);
    folds.set(def.id, {section, header, body});
    const open = remembered(def.id, def.open);
    body.hidden = !open;
    header.setAttribute("aria-expanded", String(open));
  }
  // A bar above the sections: fold everything away, then bring back what was open.
  const bar = document.createElement("div");
  bar.className = "fold-toolbar";
  const toggle = Object.assign(document.createElement("button"), {type: "button", textContent: "Collapse all",
    title: "Fold every section; press again to open the ones that were open"});
  let wasOpen: string[] = [];
  const openIds = () => [...folds].filter(([, fold]) => !fold.body.hidden).map(([id]) => id);
  const syncToggle = () => { toggle.textContent = openIds().length ? "Collapse all" : "Expand all"; };
  toggle.addEventListener("click", () => {
    const open = openIds();
    if (open.length) {
      wasOpen = open;
      for (const id of open) setOpen(id, false);
    } else {
      for (const id of wasOpen.length ? wasOpen : SECTIONS.filter(def => def.open).map(def => def.id)) setOpen(id, true);
    }
    syncToggle();
  });
  document.addEventListener("ingetrazo:folds-changed", syncToggle);
  bar.append(toggle);
  aside.prepend(bar);
  aside.append(stack);

  function setOpen(id: string, open: boolean): void {
    const fold = folds.get(id)!;
    if (fold.body.hidden === !open) return;
    fold.body.hidden = !open;
    fold.header.setAttribute("aria-expanded", String(open));
    try { localStorage.setItem(storageKey(id), open ? "1" : "0"); } catch { /* session only */ }
    refresh();
    document.dispatchEvent(new CustomEvent("ingetrazo:folds-changed"));
  }

  const isEmpty = (body: HTMLElement) => [...body.children].every(
    child => child.classList.contains("fold-empty") || (child as HTMLElement).hidden
      || child.classList.contains("tray-actions"));

  function refresh(): void {
    for (const {section, body} of folds.values()) {
      // Only write on a change: this runs from an observer of the same attribute,
      // and re-setting ``hidden`` queues another mutation record (an endless loop).
      const note = body.querySelector<HTMLElement>(".fold-empty")!;
      const empty = isEmpty(body);
      if (note.hidden !== !empty) note.hidden = !empty;
      section.classList.toggle("dim", empty);
    }
  }

  new MutationObserver(refresh).observe(aside, {subtree: true, attributes: true, attributeFilter: ["hidden"]});
  // Picking an object unfolds its properties.
  const selection = document.querySelector<HTMLElement>("#selection-panel")!;
  new MutationObserver(() => { if (!selection.hidden) show("entity"); })
    .observe(selection, {attributes: true, attributeFilter: ["hidden"]});
  refresh();

  function show(id: string): void {
    const fold = folds.get(id);
    if (!fold) return;
    setOpen(id, true);
    fold.section.scrollIntoView({block: "nearest", behavior: "smooth"});
  }

  function addActions(id: string, actions: {label: string; run: () => void}[]): void {
    const row = document.createElement("div");
    row.className = "tray-actions";
    for (const action of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.textContent = action.label;
      button.addEventListener("click", action.run);
      row.append(button);
    }
    folds.get(id)!.body.prepend(row);
  }
  return {show, addActions};
}
