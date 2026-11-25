/**
 * Desktop-style chrome: menu bar, icon toolbars and status bar.
 *
 * The toolbar layout, tool names, shortcuts and icons all come from the
 * desktop application (exported once, see UPSTREAM.md; they are now this
 * repository's own assets). Each tool is bound to what the web service can do today (see
 * `BINDINGS`); a tool with no binding stays visible but disabled, which makes
 * the remaining parity gap visible instead of hiding it.
 */
import manifest from "./ui/manifest.json";
import type {Gestures} from "./gestures";
import {importModel} from "./convert";
import {openPreferences} from "./preferences";
import type {PreferencesTab} from "./preferences";
import {askParameters, listExtensions} from "./extensions";
import {mountToolbarDocking} from "./toolbars";
import {onLanguageChange, tr} from "./i18n";
import {comboOf, createShortcuts} from "./shortcuts";
import type {Selection} from "./selection";
import type {LooseEdge} from "./viewer";
import {effectiveTheme, onThemeChange} from "./theme";
import type {ToolForms} from "./toolforms";
import type {IngeTrazoViewer, NavigationMode, ViewName, WalkMode} from "./viewer";

type ToolEntry = {name: string; shortcut: string; shortcut_alt: string; description: string};
type Manifest = {
  toolbars: {id: string; title: string; tools: string[]; area: "top" | "left"; order: number}[];
  tools: Record<string, ToolEntry>;
};
const ui = manifest as Manifest;

/** How a toolbar key maps onto the web client. */
type Binding =
  | {kind: "nav"; mode: NavigationMode}
  | {kind: "view"; view: ViewName}
  | {kind: "select"}
  | {kind: "click"; target: string; hint: string}
  | {kind: "form"; form: string; hint: string; needsSelection?: boolean}
  | {kind: "panel"}
  | {kind: "zoomwindow"}
  | {kind: "walk"; mode: WalkMode; hint: string}
  | {kind: "action"; run: () => void};

export function mountChrome(viewer: IngeTrazoViewer, forms: ToolForms, gestures: Gestures, selection: Selection): void {
  const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
  const hint = $("#tool-hint");
  const toolbars = $("#toolbars");
  const menubar = $("#menubar");
  const buttons = new Map<string, HTMLButtonElement>();
  const clickLegacy = (selector: string) => document.querySelector<HTMLElement>(selector)?.click();
  const legacyActive = (selector: string) => document.querySelector(selector)?.classList.contains("active") ?? false;

  const setHint = (text: string) => { hint.textContent = text; };
  // The desktop's keys, plus whatever this browser has customised (Ctrl+S is the browser's own).
  const shortcuts = createShortcuts(ui.tools, new Set(["save"]));

  const BINDINGS: Record<string, Binding> = {
    select: {kind: "select"},
    orbit: {kind: "nav", mode: "orbit"},
    pan: {kind: "nav", mode: "pan"},
    zoom: {kind: "nav", mode: "zoom"},
    zoom_extents: {kind: "action", run: () => viewer.fit()},
    zoom_selection: {kind: "action", run: () => viewer.fitSelection()},
    zoom_window: {kind: "zoomwindow"},
    position_camera: {kind: "walk", mode: "position_camera", hint: "Position Camera: click where the eye should stand; it is placed 1.6 m up, facing the model."},
    walk: {kind: "walk", mode: "walk", hint: "Walk: drag up/down to move forward or back, left/right to turn."},
    look_around: {kind: "walk", mode: "look_around", hint: "Look Around: drag to turn your head without moving."},
    first_person: {kind: "walk", mode: "first_person", hint: "First Person: W A S D to move (Shift runs), drag to look."},
    save: {kind: "action", run: () => clickLegacy("#save")},
    view_iso: {kind: "view", view: "iso"},
    view_top: {kind: "view", view: "top"},
    view_front: {kind: "view", view: "front"},
    view_right: {kind: "view", view: "right"},
    view_left: {kind: "view", view: "left"},
    view_back: {kind: "view", view: "back"},
    view_bottom: {kind: "view", view: "bottom"},
    line: {kind: "click", target: "#sketch-line", hint: "Line: pick two points; the second one creates the edge."},
    tape: {kind: "click", target: "#measure", hint: "Tape Measure: pick two points to read the distance."},
    rectangle: {kind: "form", form: "#create-rectangle", hint: "Rectangle: enter width, depth and origin, then Create."},
    circle: {kind: "form", form: "#create-circle", hint: "Circle: enter radius, segments and centre, then Create."},
    center_arc: {kind: "form", form: "#create-arc", hint: "Center Arc: enter radius, start and sweep, then Create."},
    dimension: {kind: "form", form: "#create-dimension", hint: "Dimension: enter endpoints and offset, then Create."},
    text: {kind: "form", form: "#create-text", hint: "Text: enter the label and anchor, then Create."},
    geopath: {kind: "form", form: "#create-geopath", hint: "Trace: enter local points, then Create."},
    pushpull: {kind: "form", form: "#push-pull-object", needsSelection: true, hint: "Push/Pull: choose the face direction and type a distance."},
    offset: {kind: "form", form: "#offset-face", needsSelection: true, hint: "Offset: type the distance for the selected face."},
    move: {kind: "form", form: "#move-object", needsSelection: true, hint: "Move: type the X/Y/Z offset for the selected object."},
    rotate: {kind: "form", form: "#rotate-object", needsSelection: true, hint: "Rotate: choose an axis and type the angle."},
    scale: {kind: "form", form: "#scale-object", needsSelection: true, hint: "Scale: type the factors for the selected object."},
    paint: {kind: "form", form: "#object-material", needsSelection: true, hint: "Paint: choose a colour and opacity for the selected object."},
    eraser: {kind: "action", run: () => {
      const remove = document.querySelector<HTMLButtonElement>("#delete-object");
      if (remove && !remove.closest("[hidden]")) remove.click();
      else setHint("Eraser: select an object first; it is then deleted as a new revision.");
    }},
    ...Object.fromEntries(
      ["arc", "arc3", "pie", "polygon", "rotated_rect", "freehand", "flip", "followme", "fillet",
        "protractor", "text3d", "section_fill", "outer_shell", "solid_union", "solid_subtract",
        "solid_trim", "solid_intersect", "solid_split"]
        .map(key => [key, {kind: "panel"} as Binding])),
    section_planes: {kind: "action", run: () => clickLegacy("#section-plane")},
    section_cuts: {kind: "action", run: () => clickLegacy("#section-cut")},
    eyedropper: {kind: "action", run: sampleMaterial},
    section: {kind: "form", form: "#sections-panel", hint: "Section Plane: use Plane / Cut and the planes listed in the Sections panel."},
  };

  /** Eyedropper: copy the picked object's colour into the Paint form. */
  function sampleMaterial(): void {
    const terms = [...document.querySelectorAll<HTMLElement>("#selection dt")];
    const term = terms.find(item => (item.dataset.i18nSource ?? item.textContent) === "Object colour");
    const colour = term?.nextElementSibling?.textContent ?? "";
    const input = document.querySelector<HTMLInputElement>("#object-material input[name=color]");
    if (!input || !/^#[0-9a-f]{6}$/i.test(colour)) {
      setHint("Sample material: pick an object that has a colour first.");
      return;
    }
    input.value = colour;
    revealForm("#object-material");
    setHint(`Sampled ${colour}; adjust it and press Paint to apply it to another object.`);
  }

  function describe(key: string): string {
    const entry = ui.tools[key];
    const keys = shortcuts.label(key);
    return `${tr(entry.name)}${keys ? `  (${keys})` : ""}${entry.description ? `\n${tr(entry.description)}` : ""}`;
  }

  function releaseModes(): void {
    for (const selector of ["#sketch-line", "#measure"]) {
      if (legacyActive(selector)) clickLegacy(selector);
    }
  }

  function revealForm(selector: string): HTMLElement | null {
    const form = document.querySelector<HTMLElement>(selector);
    if (!form || form.hidden || form.closest("[hidden]")) return null;
    for (let node: HTMLElement | null = form; node; node = node.parentElement) {
      if (node instanceof HTMLDetailsElement) node.open = true;
    }
    // Other selection code scrolls the sidebar too; scroll after it has run.
    setTimeout(() => form.scrollIntoView({block: "center", behavior: "smooth"}), 60);
    form.classList.add("tool-flash");
    setTimeout(() => form.classList.remove("tool-flash"), 900);
    form.querySelector<HTMLElement>("input, select, textarea")?.focus({preventScroll: true});
    return form;
  }

  // The tool whose form should come forward as soon as an object is picked.
  let pendingForm: {key: string; binding: Extract<Binding, {kind: "form"}>} | null = null;

  function markActive(key: string): void {
    pendingForm = null;
    for (const [name, button] of buttons) {
      if (button.dataset.toggle === "tool") button.classList.toggle("active", name === key);
    }
  }

  document.addEventListener("ingetrazo:activate", event => activate((event as CustomEvent<string>).detail));
  /** What a left-drag does with the Select tool: draw a selection box, or orbit. */
  const selectDrag = (): "box" | "orbit" => {
    try { return localStorage.getItem("ingetrazo.selectdrag") === "orbit" ? "orbit" : "box"; } catch { return "box"; }
  };
  const selectToolActive = () => document.querySelector(".tool-button.active")?.getAttribute("data-tool") === "select";
  const numericButton = $<HTMLButtonElement>("#numeric-entry");
  let numericKey: string | undefined;
  numericButton.addEventListener("click", () => { if (numericKey) activate(numericKey, true); });

  function activate(key: string, numeric = false): void {
    if (gestures.has(key) && !numeric) {
      releaseModes();
      viewer.setWalkMode(null);
      viewer.setZoomWindow(false);
      markActive(key);
      forms.hide();
      viewer.setBoxSelect(false);
      gestures.start(key);
      numericKey = BINDINGS[key] ? key : undefined;
      numericButton.hidden = !numericKey;
      return;
    }
    const binding = BINDINGS[key];
    // Camera moves and one-shot actions leave the active drawing tool alone.
    if (binding && binding.kind !== "view" && binding.kind !== "action") {
      gestures.stop();
      numericButton.hidden = true;
      viewer.setBoxSelect(false);
      if (binding.kind !== "panel") forms.hide();
    }
    if (!binding) {
      setHint(`${ui.tools[key].name} is not available in the web version yet.`);
      return;
    }
    switch (binding.kind) {
      case "nav":
        releaseModes();
        viewer.setWalkMode(null);
        viewer.setZoomWindow(false);
        viewer.setNavigation(binding.mode);
        markActive(key);
        setHint(`${ui.tools[key].name}: ${ui.tools[key].description}`);
        break;
      case "select":
        releaseModes();
        viewer.setWalkMode(null);
        viewer.setZoomWindow(false);
        viewer.setNavigation("orbit");
        viewer.setBoxSelect(selectDrag() === "box");
        markActive("select");
        setHint(selectDrag() === "box"
          ? "Select: click an object or face; drag a box (left to right: inside, right to left: touching; Shift adds). Orbit with the middle button or the Orbit tool (O)."
          : "Select: click an object or face (Shift adds); drag to orbit.");
        break;
      case "view":
        viewer.setView(binding.view);
        setHint(`${ui.tools[key].name} view.`);
        break;
      case "click":
        releaseModes();
        clickLegacy(binding.target);
        markActive(key);
        setHint(binding.hint);
        break;
      case "form": {
        releaseModes();
        markActive(key);
        const form = revealForm(binding.form);
        if (!form && binding.needsSelection) pendingForm = {key, binding};
        const picked = !$("#selection-panel").hidden;
        setHint(form || !binding.needsSelection
          ? binding.hint
          : picked
            ? `${ui.tools[key].name}: that part is nested. Choose its top-level object in the Objects list.`
            : `${ui.tools[key].name}: select an object in the model first.`);
        break;
      }
      case "zoomwindow":
        releaseModes();
        viewer.setWalkMode(null);
        viewer.setZoomWindow(true);
        markActive(key);
        setHint("Zoom Window: drag a rectangle around the area to frame.");
        break;
      case "walk":
        releaseModes();
        viewer.setWalkMode(binding.mode);
        markActive(key);
        setHint(binding.hint);
        break;
      case "panel":
        releaseModes();
        markActive(key);
        setHint(forms.show(key));
        break;
      case "action":
        binding.run();
        break;
    }
  }

  new MutationObserver(() => {
    if (!pendingForm) return;
    const {key, binding} = pendingForm;
    if (revealForm(binding.form)) {
      pendingForm = {key, binding};
      setHint(binding.hint);
    } else if (!$("#selection-panel").hidden) {
      setHint(`${ui.tools[key].name}: that part is nested. Choose its top-level object in the Objects list.`);
    }
  }).observe($("aside"), {subtree: true, attributes: true, attributeFilter: ["hidden"]});

  viewer.onToolDone = () => {
    // Zoom Window ends in Select; Position Camera continues in Look Around.
    if (buttons.get("position_camera")?.classList.contains("active")) {
      markActive("look_around");
      setHint("Camera placed. Look Around: drag to turn; Walk or First Person to move.");
    } else {
      activate("select");
    }
  };

  // --- toolbars ---------------------------------------------------------
  const iconUrl = (key: string) => `/icons/${effectiveTheme()}/${key}.png`;

  function separator(): HTMLElement {
    const sep = document.createElement("span");
    sep.className = "toolbar-sep";
    return sep;
  }

  function makeButton(key: string): HTMLButtonElement {
    const button = document.createElement("button");
    const binding = BINDINGS[key];
    button.type = "button";
    button.className = "tool-button";
    button.dataset.tool = key;
    if (gestures.has(key) || (binding && binding.kind !== "view" && binding.kind !== "action")) button.dataset.toggle = "tool";
    button.title = binding ? describe(key) : `${describe(key)}\nNot available in the web version yet.`;
    button.setAttribute("aria-label", ui.tools[key].name);
    button.disabled = !binding;
    const image = document.createElement("img");
    image.src = iconUrl(key);
    image.alt = "";
    image.width = 24;
    image.height = 24;
    button.append(image);
    button.addEventListener("click", () => activate(key));
    buttons.set(key, button);
    return button;
  }

  // The desktop's default layout: Main, Modify, View, Sections, Standard Views and
  // Solid Tools along the top; Draw, Annotate and Walkthrough in a column at the left.
  const leftColumn = $("#toolbars-left");
  const placed = [...ui.toolbars].sort((a, b) => a.order - b.order);
  for (const row of placed) {
    const group = document.createElement("div");
    group.className = `toolbar-group ${row.area === "left" ? "vertical" : ""}`;
    group.dataset.toolbar = row.id;
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", row.title);
    const grip = document.createElement("span");
    grip.className = "toolbar-grip";
    grip.setAttribute("aria-hidden", "true");
    group.append(grip);
    row.tools.forEach((key, index) => {
      group.append(makeButton(key));
      // Separators where the desktop has them: after Save, after Zoom Window.
      if ((row.id === "main" && key === "save") || (row.id === "view" && index === 3)) group.append(separator());
    });
    (row.area === "left" ? leftColumn : toolbars).append(group);
  }
  const docking = mountToolbarDocking();
  markActive("select");
  viewer.setBoxSelect(selectDrag() === "box");

  onThemeChange(() => {
    for (const [key, button] of buttons) button.querySelector("img")!.src = iconUrl(key);
  });

  // --- menu bar ---------------------------------------------------------
  type Item = {label: string; key?: string; run?: () => void; checked?: () => boolean; sep?: boolean};
  const sep: Item = {sep: true, label: ""};
  const tool = (key: string): Item => ({label: ui.tools[key].name, key, run: () => activate(key)});
  const legacy = (label: string, selector: string): Item => ({label, run: () => clickLegacy(selector)});
  const toolbar = (id: string) => ui.toolbars.find(row => row.id === id)!.tools;
  const toggle = (label: string, selector: string): Item => ({
    label, run: () => clickLegacy(selector), checked: () => $<HTMLInputElement>(selector).checked,
  });
  const extensionItems: Item[] = [{label: "Loading extensions…"}];
  const menus: {title: string; items: Item[]}[] = [
    {title: "File", items: [
      {label: "Open…", run: () => clickLegacy("#file")},
      legacy("Save to library", "#save"),
      sep,
      {label: "Import model (OBJ, STL, DAE, DXF, GLB, SKP)…", run: () => importModel(async id => { document.dispatchEvent(new CustomEvent("ingetrazo:open-document", {detail: id})); })},
      {label: "Export revision (GLB, OBJ, STL, DAE, DXF, IFC)…", run: () => document.dispatchEvent(new CustomEvent("ingetrazo:export"))},
      sep,
      legacy("Export quantities (CSV)", "#export-quantities"),
      sep,
      {label: "Sign out", run: () => document.dispatchEvent(new CustomEvent("ingetrazo:sign-out"))},
      legacy("Export IFC", "#export-ifc"),
    ]},
    {title: "Edit", items: [
      legacy("Undo", "#undo-revision"),
      legacy("Redo", "#redo-revision"),
      sep,
      legacy("Copy", "#copy-object"),
      legacy("Paste", "#paste-object"),
      legacy("Duplicate", "#duplicate-object"),
      legacy("Delete", "#delete-object"),
      sep,
      legacy("Deselect", "#clear-selection"),
      {label: "Select All", run: () => selectEverything()},
      {sep: true, label: ""},
      {label: "Make Group", run: () => gestures.groupSelection({component: false, connected: true})},
      {label: "Make Component", run: () => gestures.groupSelection({component: true, connected: true})},
      {label: "Explode", run: () => gestures.explodeSelection()},
      {label: "Join Segments", run: () => gestures.joinSegments()},
      {label: "Explode Curve", run: () => gestures.explodeCurve()},
      {label: "Change Segments…", run: () => { void gestures.resegmentSelection(); }},
      {label: "Bridge", run: () => gestures.bridgeSelection()},
      {label: "Scale…", run: () => { void gestures.scaleSelection(); }},
      {sep: true, label: ""},
      {label: "Make Faces and Extrude…", run: () => { void gestures.makeFacesExtrude(); }},
      {label: "Cut Opening", run: () => gestures.cutOpening(true)},
      {label: "Close Opening", run: () => gestures.cutOpening(false)},
    ]},
    {title: "Camera", items: [
      ...["orbit", "pan", "zoom", "zoom_extents"].map(tool),
      sep,
      ...toolbar("views").map(tool),
      sep,
      legacy("Perspective / Orthographic", "#projection"),
      toggle("Edges", "#edges"),
      toggle("Grid", "#grid"),
      toggle("Axes", "#axes"),
    ]},
    {title: "Draw", items: [...toolbar("draw").map(tool), sep, {label: "Terrain…", run: () => { void gestures.createTerrain(); }}]},
    {title: "Tools", items: [
      ...toolbar("modify").map(tool), sep,
      ...toolbar("annotate").map(tool), sep,
      tool("section"), ...toolbar("solids").map(tool),
    ]},
    {title: "Extensions", items: extensionItems},
    {title: "Window", items: [{label: "Preferences…", run: () => showPreferences()}, {label: "Reset toolbar layout", run: () => docking.reset()}, sep, ...ui.toolbars.map(row => ({
      label: row.title,
      checked: () => !document.querySelector<HTMLElement>(`[data-toolbar="${row.id}"]`)!.hidden,
      run: () => {
        const group = document.querySelector<HTMLElement>(`[data-toolbar="${row.id}"]`)!;
        group.hidden = !group.hidden;
      },
    }))]},
    {title: "Help", items: [
      {label: "Keyboard shortcuts", run: () => showPreferences("shortcuts")},
      {label: "About IngeTrazo Web", run: () => setHint("IngeTrazo Web: the browser client for IngeTrazo .igz documents.")},
    ]},
  ];

  void listExtensions().then(({directory, extensions}) => {
    extensionItems.length = 0;
    for (const extension of extensions) {
      extensionItems.push({
        label: extension.error ? `⚠ ${extension.name} (load error)` : `${extension.name}…`,
        run: extension.error
          ? () => setHint(`${extension.name} did not load: ${extension.error}`)
          : async () => {
            const params = extension.parameters.length ? await askParameters(extension) : {};
            if (params) document.dispatchEvent(new CustomEvent("ingetrazo:run-extension", {detail: {key: extension.key, name: extension.name, params}}));
          },
      });
    }
    if (!extensions.length) extensionItems.push({label: "No extensions installed", run: () => setHint(`Put extension .py files in ${directory || "the server's extensions folder"} (see web/README.md).`)});
  });

  let openPanel: HTMLElement | null = null;
  function closeMenu(): void {
    openPanel?.remove();
    openPanel = null;
    menubar.querySelectorAll(".open").forEach(node => node.classList.remove("open"));
  }

  for (const menu of menus) {
    const title = document.createElement("button");
    title.type = "button";
    title.className = "menu-title";
    title.textContent = menu.title;
    title.setAttribute("aria-haspopup", "true");
    const show = () => {
      closeMenu();
      const panel = document.createElement("div");
      panel.className = "menu-panel";
      panel.setAttribute("role", "menu");
      for (const item of menu.items) {
        if (item.sep) { panel.append(document.createElement("hr")); continue; }
        const entry = document.createElement("button");
        entry.type = "button";
        entry.className = "menu-item";
        entry.setAttribute("role", "menuitem");
        entry.disabled = Boolean(item.key) && !BINDINGS[item.key!];
        const icon = document.createElement("span");
        icon.className = "menu-icon";
        if (item.key) {
          const image = document.createElement("img");
          image.src = iconUrl(item.key);
          image.alt = "";
          image.width = 16;
          image.height = 16;
          icon.append(image);
        } else if (item.checked) {
          icon.textContent = item.checked() ? "✓" : "";
        }
        const label = document.createElement("span");
        label.textContent = item.label;
        const keys = document.createElement("span");
        keys.className = "menu-keys";
        if (item.key) keys.textContent = shortcuts.label(item.key);
        entry.append(icon, label, keys);
        entry.addEventListener("click", () => { closeMenu(); item.run?.(); });
        panel.append(entry);
      }
      title.classList.add("open");
      title.after(panel);
      openPanel = panel;
    };
    title.addEventListener("click", event => {
      event.stopPropagation();
      if (title.classList.contains("open")) closeMenu(); else show();
    });
    title.addEventListener("mouseenter", () => { if (openPanel && !title.classList.contains("open")) show(); });
    menubar.append(title);
  }
  document.addEventListener("click", closeMenu);

  const toolbarPx = () => Number(document.documentElement.style.getPropertyValue("--tool-px").replace("px", "")) || 32;
  function showPreferences(tab: PreferencesTab = "general"): void {
    openPreferences({
      shortcutsPanel: () => shortcuts.panel(),
      selectDrag,
      setSelectDrag: value => {
        try { localStorage.setItem("ingetrazo.selectdrag", value); } catch { /* session only */ }
        if (selectToolActive()) activate("select");
      },
      toolbarPx,
      setToolbarPx: px => {
        document.documentElement.style.setProperty("--tool-px", `${px}px`);
        try { localStorage.setItem("ingetrazo.toolpx", String(px)); } catch { /* session only */ }
      },
    }, tab);
  }
  document.addEventListener("ingetrazo:preferences", event => showPreferences(((event as CustomEvent<PreferencesTab>).detail) ?? "general"));

  try {
    const saved = localStorage.getItem("ingetrazo.toolpx");
    if (saved) document.documentElement.style.setProperty("--tool-px", `${Number(saved)}px`);
  } catch { /* no storage */ }

  const vcbBox = $<HTMLInputElement>("#vcb");
  vcbBox.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      gestures.enter(vcbBox.value);
      vcbBox.value = "";
      vcbBox.blur();
    } else if (event.key === "Escape") {
      vcbBox.value = "";
      vcbBox.blur();
      gestures.cancel();
    }
  });

  // --- group edit context: double-click enters, double-click on nothing leaves ---
  const contextLabel = document.createElement("span");
  contextLabel.className = "context-label";
  contextLabel.hidden = true;
  document.querySelector(".statusbar")!.insertBefore(contextLabel, document.querySelector(".vcb"));
  viewer.onContextChange = id => {
    selection.setFaces([]);             // face numbers belong to the object they were picked in
    document.dispatchEvent(new CustomEvent("ingetrazo:context"));
    contextLabel.hidden = !id;
    contextLabel.textContent = id ? `Editing ${describeObject(id)} (double-click empty space or Esc to leave)` : "";
  };
  const describeObject = (id: string) => document.querySelector(`#outline li[data-object-id="${id}"] strong`)?.textContent ?? id;
  function enterContext(full: string | undefined): void {
    const current = viewer.getEditContext();
    if (!full) {
      if (current) viewer.setEditContext(current.includes("/") ? current.slice(0, current.lastIndexOf("/")) : undefined);
      return;
    }
    const depth = current ? current.split("/").length + 1 : 1;
    const parts = full.split("/");
    if (parts.length < depth) return;
    const target = parts.slice(0, depth).join("/");
    viewer.setEditContext(target);
    viewer.selectObject(target);
  }
  canvas0().addEventListener("dblclick", event => {
    if (gestures.active()) return;
    enterContext(viewer.fullIdAt(event.clientX, event.clientY));
  });
  function canvas0(): HTMLCanvasElement { return $<HTMLCanvasElement>("#viewer"); }

  // --- editing shortcuts and the canvas context menu ----------------------
  const visible = (selector: string): HTMLElement | null => {
    const node = document.querySelector<HTMLElement>(selector);
    return node && !node.hidden && !node.closest("[hidden]") ? node : null;
  };
  document.addEventListener("keydown", event => {
    const target = event.target as HTMLElement | null;
    if (target && (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName))) return;
    const mod = event.ctrlKey || event.metaKey;
    const key = event.key.toLowerCase();
    let handled = true;
    if (mod && key === "z" && !event.shiftKey) clickLegacy("#undo-revision");
    else if (mod && (key === "y" || (key === "z" && event.shiftKey))) clickLegacy("#redo-revision");
    else if (mod && key === "c") clickLegacy("#copy-object");
    else if (mod && key === "v") clickLegacy("#paste-object");
    else if (mod && key === "d") clickLegacy("#duplicate-object");
    else if (mod && key === "s") clickLegacy("#save");
    else if (mod && key === "o") clickLegacy("#file");
    else if (!mod && (key === "delete" || key === "backspace")) {
      if (!selection.isEmpty()) gestures.deleteSelection();
      else if (visible("#delete-object")) clickLegacy("#delete-object");
    }
    else if (mod && key === "g") gestures.groupSelection({component: false, connected: true});
    else if (mod && key === "a") selectEverything();
    else handled = false;
    if (handled) event.preventDefault();
  });

  /** Ctrl+A: every top-level object in the open document. */
  function selectEverything(): void {
    const ids = [...document.querySelectorAll<HTMLElement>("#outline > li")].map(item => item.dataset.objectId!).filter(Boolean);
    selection.setObjects(ids);
    setHint(`${ids.length} objects selected.`);
  }

  const canvas = $<HTMLCanvasElement>("#viewer");
  let rightDown: {x: number; y: number} | undefined;
  canvas.addEventListener("pointerdown", event => { if (event.button === 2) rightDown = {x: event.clientX, y: event.clientY}; });
  canvas.addEventListener("contextmenu", event => {
    event.preventDefault();
    // A right-drag pans; only a still right-click opens the menu.
    if (rightDown && Math.hypot(event.clientX - rightDown.x, event.clientY - rightDown.y) > 4) return;
    const snap = viewer.snapAt(event.clientX, event.clientY);
    openContextMenu(event.clientX, event.clientY, snap?.objectId, snap?.objectName, snap?.looseFace, snap?.looseEdge, snap?.point);
  });

  function openContextMenu(x: number, y: number, objectId?: string, objectName?: string, looseFace?: number, looseEdge?: LooseEdge, clickPoint?: [number, number, number]): void {
    closeMenu();
    const items: Item[] = [];
    const pick = () => { if (objectId) viewer.selectObject(objectId); };
    if (looseFace === undefined && looseEdge) {
      // A free loose edge: it joins the selection unless it is already in it.
      const ensure = () => { if (!selection.hasEdge(looseEdge)) selection.setEdges([looseEdge]); };
      const act = (label: string, run: () => void): Item => ({label, run: () => { ensure(); setTimeout(run, 20); }});
      const count = selection.hasEdge(looseEdge) ? selection.edges().length : 1;
      items.push(
        {label: count > 1 ? `${count} edges (loose geometry)` : "Edge (loose geometry)", run: ensure},
        sep,
        act("Join Segments", () => gestures.joinSegments()),
        act("Explode Curve", () => gestures.explodeCurve()),
        act("Make Faces and Extrude…", () => { void gestures.makeFacesExtrude(); }),
        act("Change Segments…", () => { void gestures.resegmentSelection(); }),
        act("Bridge", () => gestures.bridgeSelection()),
        sep,
        act("Erase", () => gestures.deleteSelection()),
      );
    } else if (looseFace !== undefined) {
      // A face that is not part of any group: its own editing commands.
      const ensure = () => { if (!selection.faces().includes(looseFace)) selection.setFaces([looseFace]); };
      const act = (label: string, run: () => void): Item => ({label, run: () => { ensure(); setTimeout(run, 20); }});
      items.push(
        {label: `Face ${looseFace} (loose geometry)`, run: ensure},
        sep,
        act("Push/Pull", () => activate("pushpull")),
        act("Paint", () => activate("paint")),
        act("Select connected", () => { void gestures.selectConnected(); }),
        act("Make group", () => gestures.groupSelection({component: false, connected: true})),
        act("Make component", () => gestures.groupSelection({component: true, connected: true})),
        act("Bridge", () => gestures.bridgeSelection()),
        sep,
        act("Erase", () => gestures.deleteSelection()),
      );
    } else if (objectId) {
      // The clicked object joins the selection unless it is already part of it.
      const ensure = () => { if (!selection.objects().includes(objectId)) selection.setObjects([objectId]); };
      const act = (label: string, run: () => void): Item => ({label, run: () => { pick(); ensure(); setTimeout(run, 30); }});
      items.push(
        {label: objectName ?? objectId, run: pick},
        sep,
        act("Move", () => activate("move")),
        act("Rotate", () => activate("rotate")),
        act("Scale", () => activate("scale")),
        act("Flip…", () => activate("flip")),
        act("Paint…", () => activate("paint", true)),
        sep,
        act("Make group", () => gestures.groupSelection({component: false, connected: true})),
        act("Make component", () => gestures.groupSelection({component: true, connected: true})),
        act("Explode", () => gestures.explodeSelection()),
        act("Scale…", () => { void gestures.scaleSelection(); }),
        act("Cut Opening", () => gestures.cutOpening(true)),
        act("Close Opening", () => gestures.cutOpening(false)),
        ...(clickPoint ? [act("Raise or Lower Ground Here…", () => { void gestures.deformTerrain(objectId, clickPoint); })] : []),
        sep,
        act("Rename…", () => { void renameSelected(); }),
        act("Duplicate", () => clickLegacy("#duplicate-object")),
        act("Copy", () => clickLegacy("#copy-object")),
        act("Hide", () => document.querySelector<HTMLElement>(`#outline li[data-object-id="${objectId}"] .visibility-object`)?.click()),
        act("Edit inside", () => enterContext(objectId)),
        act("Zoom to object", () => viewer.fitSelection()),
        sep,
        act("Delete", () => clickLegacy("#delete-object")),
      );
    } else {
      items.push(
        {label: "Zoom Extents", run: () => viewer.fit()},
        legacy("Paste", "#paste-object"),
        sep,
        ...["view_iso", "view_top", "view_front", "view_right"].map(tool),
        sep,
        {label: "Select tool", run: () => activate("select")},
      );
    }
    const panel = document.createElement("div");
    panel.className = "menu-panel context-menu";
    panel.setAttribute("role", "menu");
    for (const item of items) {
      if (item.sep) { panel.append(document.createElement("hr")); continue; }
      const entry = document.createElement("button");
      entry.type = "button";
      entry.className = "menu-item";
      entry.style.gridTemplateColumns = "1fr auto";
      entry.setAttribute("role", "menuitem");
      const label = document.createElement("span");
      label.textContent = item.label;
      const keys = document.createElement("span");
      keys.className = "menu-keys";
      if (item.key) keys.textContent = ui.tools[item.key].shortcut;
      entry.append(label, keys);
      entry.addEventListener("click", () => { closeMenu(); item.run?.(); });
      panel.append(entry);
    }
    panel.style.left = `${Math.min(x, window.innerWidth - 230)}px`;
    panel.style.top = `${Math.min(y, window.innerHeight - items.length * 28 - 16)}px`;
    document.body.append(panel);
    openPanel = panel;
  }

  async function renameSelected(): Promise<void> {
    const input = document.querySelector<HTMLInputElement>("#object-name");
    if (!input) return;
    const answer = window.prompt("New name", input.value);
    if (answer && answer.trim()) {
      input.value = answer.trim();
      clickLegacy("#rename-object");
    }
  }

  onLanguageChange(() => {
    for (const [key, button] of buttons) button.title = BINDINGS[key] ? describe(key) : `${describe(key)}\nNot available in the web version yet.`;
  });
  // --- keyboard shortcuts: the desktop's keys, as customised --------------
  shortcuts.onChange(() => {
    for (const [key, button] of buttons) {
      button.title = BINDINGS[key] ? describe(key) : `${describe(key)}\nNot available in the web version yet.`;
    }
  });
  document.addEventListener("keydown", event => {
    const target = event.target as HTMLElement | null;
    if (target && (target.isContentEditable || /^(input|textarea|select)$/i.test(target.tagName))) return;
    if (["Shift", "Control", "Alt", "Meta"].includes(event.key)) return;
    if (event.key === "Escape") {
      closeMenu();
      if (gestures.active()) { gestures.cancel(); return; }
      if (viewer.getEditContext()) { enterContext(undefined); return; }
      activate("select");
      return;
    }
    // Typing a number while a drawing tool is active goes to the Measurements box.
    if (gestures.active() && /^[0-9.,;+\-]$/.test(event.key) && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const box = $<HTMLInputElement>("#vcb");
      box.focus();
      box.value = event.key;
      event.preventDefault();
      return;
    }
    const combo = comboOf(event);
    const key = combo ? shortcuts.lookup(combo) : undefined;
    if (!key) return;
    event.preventDefault();
    activate(key);
  });
}
