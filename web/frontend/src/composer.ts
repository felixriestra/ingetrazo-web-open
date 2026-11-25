/**
 * Sheet composer: a paper page you lay out in the browser.
 *
 * The page itself is a PNG the server draws with the desktop composer's own routines
 * (so what you see is what the PDF holds); over it sits one box per item that you drag
 * to move and resize. The right-hand panel edits the selected item's fields, or the
 * page's. Every change is one ``sheet-edit`` command, so each is a revision and can be
 * undone from the revision history like any other edit.
 */
import {responseApiError} from "./api";
import {askText, confirmDialog, notice} from "./dialogs";

interface Item {id: string; list: string; label: string; x_mm: number; y_mm: number; w_mm: number; h_mm: number;
  z: number; hidden: boolean; locked: boolean; fields: Record<string, unknown>}
interface Layout {index: number; name: string; paper: string; landscape: boolean; page_mm: [number, number]; margin_mm: number;
  border: {on: boolean; mm: number; color: string; radius_mm: number; style: string};
  papers: string[]; items: Item[]; scenes: string[]; layers: string[]; addable: string[]}
interface Revised {id: string; latest_revision: number}

export interface ComposerDeps {
  record: () => {id: string; latest_revision: number} | undefined;
  /** Open a revision made by the composer in the main window. */
  revisionMade: (revised: unknown) => void;
}

const OPTIONS: Record<string, string[]> = {
  kind: ["linea", "flecha", "rect", "elipse", "poligono", "terreno"], fit: ["stretch", "cover", "contain"],
  shape: ["rect", "rounded", "ellipse"], layout: ["grid", "banded", "minimal"], corner: ["square", "rounded", "chamfer"],
  align: ["left", "center", "right"], title_align: ["left", "center", "right"], title_pos: ["below", "above"],
  title_style: ["layout", "bar", "simple"], scale_pos: ["under-left", "under-right", "inside-bl", "inside-br"],
  cut_fill: ["solid", "hatch", "none"], ground: ["ticks", "hatch", "band"],
  style: ["sombreado", "vectorial", "style:Hidden line", "style:Architectural", "tecnico", "lineas"],
};
const HIDDEN = new Set(["uid", "group_id", "frame_uid", "z", "list_name", "locked", "hidden", "path", "rows", "campos",
  "cam_target", "cam_yaw", "cam_pitch", "cam_distance", "cam_fov", "follow", "x_mm", "y_mm", "w_mm", "h_mm"]);
const COLOURS = new Set(["color", "fill_color", "label_color", "text_color", "line_color", "bg_color", "border_color", "cut_fill_color"]);
const ADD_LABELS: [string, string][] = [["frames", "View"], ["texts", "Text"], ["images", "Image…"], ["nortes", "North arrow"],
  ["scalebars", "Scale bar"], ["leyendas", "Legend"], ["shapes", "Shape"], ["cajetin", "Title block"]];

export async function openComposer(deps: ComposerDeps, sheetIndex: number): Promise<void> {
  const record = deps.record();
  if (!record) return;
  let revision = record.latest_revision;
  const documentId = record.id;
  let layout: Layout;
  let selected: string | undefined;
  let zoom = 0;                           // px per mm; 0 = fit the page to the window
  let busy = false;

  const root = document.createElement("div");
  root.className = "composer";
  root.innerHTML = `
    <header class="composer-bar">
      <strong class="composer-title"></strong>
      <span class="composer-actions"></span>
      <span class="composer-status muted"></span>
    </header>
    <div class="composer-body">
      <aside class="composer-side">
        <h3>Add</h3><div class="composer-add"></div>
        <h3>Items</h3><ul class="composer-items"></ul>
      </aside>
      <main class="composer-stage"><div class="composer-page"><img alt="Sheet preview" draggable="false"><div class="composer-boxes"></div></div></main>
      <aside class="composer-props"></aside>
    </div>`;
  document.body.append(root);
  const $ = <T extends HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  const title = $("strong.composer-title");
  const actions = $(".composer-actions");
  const statusText = $(".composer-status");
  const addBox = $(".composer-add");
  const list = $("ul.composer-items");
  const stage = $("main.composer-stage");
  const page = $(".composer-page");
  const picture = $<HTMLImageElement>("img");
  const boxes = $(".composer-boxes");
  const props = $("aside.composer-props");

  const close = () => { document.removeEventListener("keydown", onKey, true); root.remove(); };
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape" && !(event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLTextAreaElement)) {
      event.stopPropagation();
      close();
    }
  };
  document.addEventListener("keydown", onKey, true);

  const url = (path: string) => `/api/v1/documents/${encodeURIComponent(documentId)}/revisions/${revision}/${path}`;

  async function loadLayout(): Promise<void> {
    const response = await fetch(url(`sheets/${sheetIndex}/layout`));
    if (!response.ok) { notice("Sheet composer", "That sheet no longer exists."); close(); return; }
    layout = await response.json() as Layout;
    if (selected && !layout.items.some(item => item.id === selected)) selected = undefined;
    render();
    refreshPicture();
  }

  /** Fast preview first (frames outlined), then the exact drawing once the server has it. */
  function refreshPicture(): void {
    const dpi = 80;
    picture.src = url(`sheets/${sheetIndex}.png?dpi=${dpi}&frames=false`);
    const full = new Image();
    const mine = revision;
    full.onload = () => { if (mine === revision) picture.src = full.src; };
    full.src = url(`sheets/${sheetIndex}.png?dpi=${dpi}`);
  }

  async function send(ops: Record<string, unknown>[], message = "sheet edited"): Promise<boolean> {
    if (busy) return false;
    busy = true;
    statusText.textContent = "Saving…";
    try {
      const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}/commands/sheet-edit`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({base_revision: revision, sheet_index: sheetIndex, ops})});
      if (!response.ok) {
        notice("That change was refused", (await responseApiError(response)).message);
        statusText.textContent = "";
        return false;
      }
      const revised = await response.json() as Revised;
      revision = revised.latest_revision;
      deps.revisionMade(revised);
      statusText.textContent = `Revision ${revision} · ${message}`;
      await loadLayout();
      return true;
    } catch (error) {
      notice("Sheet composer", error instanceof Error ? error.message : String(error));
      return false;
    } finally { busy = false; }
  }

  // --- page, boxes, list ------------------------------------------------------
  const scale = () => zoom || Math.max(0.5, Math.min((stage.clientWidth - 40) / layout.page_mm[0], (stage.clientHeight - 40) / layout.page_mm[1]));

  function render(): void {
    title.textContent = layout.name;
    const pxPerMm = scale();
    page.style.width = `${layout.page_mm[0] * pxPerMm}px`;
    page.style.height = `${layout.page_mm[1] * pxPerMm}px`;
    boxes.replaceChildren();
    for (const item of [...layout.items].sort((a, b) => a.z - b.z)) {
      if (item.hidden) continue;
      const box = document.createElement("div");
      box.className = `composer-box${item.id === selected ? " selected" : ""}${item.locked ? " locked" : ""}`;
      const width = Math.max(item.w_mm, 4);
      const height = Math.max(item.h_mm, 4);
      Object.assign(box.style, {left: `${item.x_mm * pxPerMm}px`, top: `${item.y_mm * pxPerMm}px`,
        width: `${width * pxPerMm}px`, height: `${height * pxPerMm}px`});
      box.title = item.label;
      box.addEventListener("pointerdown", event => beginDrag(event, item, box, "move"));
      if (item.id === selected && !item.locked && "w_mm" in item.fields) {
        const handle = document.createElement("span");
        handle.className = "composer-handle";
        handle.addEventListener("pointerdown", event => { event.stopPropagation(); beginDrag(event, item, box, "resize"); });
        box.append(handle);
      }
      boxes.append(box);
    }
    list.replaceChildren();
    for (const item of [...layout.items].reverse()) {
      const row = document.createElement("li");
      row.className = item.id === selected ? "selected" : "";
      const name = Object.assign(document.createElement("button"), {type: "button", textContent: item.label, className: "composer-item-name"});
      name.addEventListener("click", () => select(item.id));
      const eye = Object.assign(document.createElement("button"), {type: "button", className: "layer-button", textContent: item.hidden ? "Show" : "Hide",
        title: item.hidden ? "Show on the sheet" : "Hide from the sheet and the PDF"});
      eye.addEventListener("click", () => void send([{op: "set", id: item.id, changes: {hidden: !item.hidden}}]));
      row.append(name, eye);
      list.append(row);
    }
    renderActions();
    renderProps();
  }

  function select(id: string | undefined): void {
    selected = id;
    render();
  }

  function beginDrag(event: PointerEvent, item: Item, box: HTMLElement, mode: "move" | "resize"): void {
    if (event.button !== 0) return;
    event.preventDefault();
    if (selected !== item.id) { selected = item.id; render(); return; }
    if (item.locked) return;
    const pxPerMm = scale();
    const start = {x: event.clientX, y: event.clientY};
    const origin = {x: item.x_mm, y: item.y_mm, w: Math.max(item.w_mm, 4), h: Math.max(item.h_mm, 4)};
    const target = box;
    let changed = false;
    const snap = (value: number) => Math.round(value * 2) / 2;
    const move = (e: PointerEvent) => {
      const dx = (e.clientX - start.x) / pxPerMm;
      const dy = (e.clientY - start.y) / pxPerMm;
      if (!changed && Math.hypot(dx, dy) * pxPerMm < 3) return;
      changed = true;
      if (mode === "move") {
        target.style.left = `${snap(origin.x + dx) * pxPerMm}px`;
        target.style.top = `${snap(origin.y + dy) * pxPerMm}px`;
      } else {
        target.style.width = `${Math.max(2, snap(origin.w + dx)) * pxPerMm}px`;
        target.style.height = `${Math.max(2, snap(origin.h + dy)) * pxPerMm}px`;
      }
    };
    const up = (e: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (!changed) return;
      const dx = (e.clientX - start.x) / pxPerMm;
      const dy = (e.clientY - start.y) / pxPerMm;
      const changes = mode === "move" ? {x_mm: snap(origin.x + dx), y_mm: snap(origin.y + dy)}
        : {w_mm: Math.max(2, snap(origin.w + dx)), ...("h_mm" in item.fields ? {h_mm: Math.max(2, snap(origin.h + dy))} : {})};
      void send([{op: "set", id: item.id, changes}], mode === "move" ? "moved" : "resized");
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function button(label: string, run: () => void, titleText = ""): HTMLButtonElement {
    const element = Object.assign(document.createElement("button"), {type: "button", textContent: label, className: "secondary-button", title: titleText});
    element.addEventListener("click", run);
    return element;
  }

  function renderActions(): void {
    actions.replaceChildren();
    const fit = button("Fit page", () => { zoom = 0; render(); });
    const bigger = button("＋", () => { zoom = scale() * 1.25; render(); }, "Zoom in");
    const smaller = button("－", () => { zoom = scale() / 1.25; render(); }, "Zoom out");
    const pdf = Object.assign(document.createElement("a"), {className: "secondary-button", textContent: "Export PDF", href: url(`sheets/${sheetIndex}.pdf`), download: ""});
    const remove = button("Delete sheet", async () => {
      if (!(await confirmDialog("Delete sheet", `Delete the sheet «${layout.name}»?`))) return;
      const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}/commands/delete-sheet`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({base_revision: revision, sheet_index: sheetIndex})});
      if (!response.ok) { notice("Sheet composer", await response.text()); return; }
      deps.revisionMade(await response.json());
      close();
    });
    const done = button("Close", close);
    actions.append(fit, smaller, bigger, pdf, remove, done);
    addBox.replaceChildren();
    for (const [key, label] of ADD_LABELS) {
      if (key === "cajetin" && layout.items.some(item => item.list === "cajetin")) continue;
      addBox.append(button(label, async () => {
        if (key === "images") { await addImage(); return; }
        await send([{op: "add", list: key}], `${label.toLowerCase()} added`);
        const added = layout.items.filter(item => item.list === key).at(-1);
        if (added) select(added.id);
      }));
    }
  }

  async function addImage(): Promise<void> {
    const picker = Object.assign(document.createElement("input"), {type: "file", accept: "image/png,image/jpeg,image/webp"});
    picker.addEventListener("change", async () => {
      const file = picker.files?.[0];
      if (!file) return;
      if (file.size > 8_000_000) { notice("Image", "The image is larger than 8 MB."); return; }
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
      await send([{op: "add", list: "images", image_base64: btoa(binary), fields: {list_name: file.name.slice(0, 60)}}], "image added");
      const added = layout.items.filter(item => item.list === "images").at(-1);
      if (added) select(added.id);
    });
    picker.click();
  }

  // --- properties ---------------------------------------------------------------
  function field(label: string, control: HTMLElement): HTMLLabelElement {
    const wrapper = document.createElement("label");
    wrapper.className = "composer-field";
    wrapper.append(Object.assign(document.createElement("span"), {textContent: label.replace(/_/g, " ")}), control);
    return wrapper;
  }

  function control(name: string, value: unknown, apply: (v: unknown) => void, layoutNow: Layout): HTMLElement | undefined {
    if (typeof value === "boolean") {
      const box = Object.assign(document.createElement("input"), {type: "checkbox", checked: value});
      box.addEventListener("change", () => apply(box.checked));
      return box;
    }
    if (name === "view_key") {
      const select = document.createElement("select");
      for (const [key, text] of [["__current__", "Current view"], ["std:top", "Top"], ["std:bottom", "Bottom"], ["std:front", "Front"],
        ["std:back", "Back"], ["std:left", "Left"], ["std:right", "Right"], ["std:iso", "Isometric"],
        ...layoutNow.scenes.map(scene => [`scene:${scene}`, `Scene · ${scene}`])]) select.append(new Option(text, key, false, key === value));
      select.addEventListener("change", () => apply(select.value));
      return select;
    }
    if (name in OPTIONS && typeof value === "string") {
      const select = document.createElement("select");
      const choices = OPTIONS[name].includes(value) ? OPTIONS[name] : [...OPTIONS[name], value];
      for (const choice of choices) select.append(new Option(choice, choice, false, choice === value));
      select.addEventListener("change", () => apply(select.value));
      return select;
    }
    if (COLOURS.has(name) && typeof value === "string") {
      const wrap = document.createElement("span");
      const input = Object.assign(document.createElement("input"), {type: "color", value: /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"});
      input.addEventListener("change", () => apply(input.value));
      wrap.append(input);
      if (value === "" || name === "bg_color" || name === "fill_color") {
        const clear = Object.assign(document.createElement("button"), {type: "button", textContent: "none", className: "layer-button"});
        clear.addEventListener("click", () => apply(""));
        wrap.append(clear);
        if (value === "") input.style.opacity = ".35";
      }
      return wrap;
    }
    if (typeof value === "number") {
      const input = Object.assign(document.createElement("input"), {type: "number", value: String(Math.round(value * 1000) / 1000), step: "any"});
      input.addEventListener("change", () => { if (Number.isFinite(input.valueAsNumber)) apply(input.valueAsNumber); });
      return input;
    }
    if (typeof value === "string") {
      const multiline = name === "text" || value.includes("\n");
      const input = multiline ? Object.assign(document.createElement("textarea"), {value, rows: 3}) : Object.assign(document.createElement("input"), {type: "text", value, maxLength: 4000});
      input.addEventListener("change", () => apply(input.value));
      return input;
    }
    return undefined;
  }

  function renderProps(): void {
    props.replaceChildren();
    const item = layout.items.find(candidate => candidate.id === selected);
    if (!item) { renderPageProps(); return; }
    props.append(Object.assign(document.createElement("h3"), {textContent: item.label}));
    const change = (changes: Record<string, unknown>) => void send([{op: "set", id: item.id, changes}]);
    const geometry = document.createElement("div");
    geometry.className = "composer-geometry";
    for (const name of ["x_mm", "y_mm", "w_mm", "h_mm"]) {
      if (!(name in item.fields) && !(name === "w_mm" && item.w_mm) ) continue;
      if (!(name in item.fields)) continue;
      const input = control(name, item.fields[name], value => change({[name]: value}), layout);
      if (input) geometry.append(field(name.replace("_mm", " (mm)"), input));
    }
    props.append(geometry);
    const flags = document.createElement("div");
    flags.className = "composer-flags";
    for (const name of ["locked", "hidden"]) {
      const input = control(name, item.fields[name], value => change({[name]: value}), layout)!;
      flags.append(field(name, input));
    }
    props.append(flags);
    for (const [name, value] of Object.entries(item.fields)) {
      if (HIDDEN.has(name)) continue;
      const input = control(name, value, v => change({[name]: v}), layout);
      if (input) props.append(field(name, input));
    }
    if (Array.isArray(item.fields.rows)) {
      const area = Object.assign(document.createElement("textarea"), {rows: 5, value: (item.fields.rows as string[]).join("\n")});
      area.addEventListener("change", () => change({rows: area.value.split("\n").map(row => row.trim()).filter(Boolean)}));
      props.append(field("rows (one per line)", area));
    }
    if (Array.isArray(item.fields.campos)) props.append(fieldTable(item));
    const tools = document.createElement("div");
    tools.className = "composer-tools";
    tools.append(
      button("Bring to front", () => void send([{op: "order", id: item.id, to: "front"}])),
      button("Send to back", () => void send([{op: "order", id: item.id, to: "back"}])));
    if (item.list !== "cajetin") tools.append(button("Duplicate", () => void send([{op: "duplicate", id: item.id}])));
    if (item.list === "frames") {
      tools.append(button("Fit to page", () => {
        const [w, h] = layout.page_mm;
        change({x_mm: layout.margin_mm, y_mm: layout.margin_mm, w_mm: w - 2 * layout.margin_mm, h_mm: h - 2 * layout.margin_mm});
      }));
    }
    tools.append(button("Rename…", async () => {
      const next = await askText("Rename item", "Name:", String(item.fields.list_name ?? ""));
      if (next !== null) change({list_name: next});
    }), button("Delete", () => void send([{op: "remove", id: item.id}], "item deleted")));
    props.append(tools);
  }

  function fieldTable(item: Item): HTMLElement {
    const table = document.createElement("table");
    table.className = "composer-fields";
    const rows = (item.fields.campos as string[][]).map(row => [...row]);
    const save = () => void send([{op: "set", id: item.id, changes: {campos: rows}}]);
    rows.forEach((row, index) => {
      const tr = table.insertRow();
      for (const column of [0, 1]) {
        const input = Object.assign(document.createElement("input"), {type: "text", value: row[column], maxLength: 400});
        input.addEventListener("change", () => { rows[index][column] = input.value; save(); });
        tr.insertCell().append(input);
      }
      const remove = Object.assign(document.createElement("button"), {type: "button", textContent: "✕", className: "layer-button"});
      remove.addEventListener("click", () => { rows.splice(index, 1); save(); });
      tr.insertCell().append(remove);
    });
    const add = button("Add row", () => { rows.push(["LABEL", ""]); save(); });
    const wrap = document.createElement("div");
    wrap.append(Object.assign(document.createElement("h4"), {textContent: "Title block rows"}), table, add);
    return wrap;
  }

  function renderPageProps(): void {
    props.append(Object.assign(document.createElement("h3"), {textContent: "Page"}));
    const change = (changes: Record<string, unknown>) => void send([{op: "page", changes}], "page set");
    const paper = document.createElement("select");
    for (const size of layout.papers) paper.append(new Option(size, size, false, size === layout.paper));
    paper.addEventListener("change", () => change({paper: paper.value}));
    props.append(field("paper", paper));
    const rows: [string, unknown][] = [["name", layout.name], ["landscape", layout.landscape], ["margin_mm", layout.margin_mm],
      ["border", layout.border.on], ["border_mm", layout.border.mm], ["border_color", layout.border.color], ["border_radius_mm", layout.border.radius_mm]];
    for (const [name, value] of rows) {
      const input = control(name === "border" ? "border" : name, value, v => change({[name]: v}), layout);
      if (input) props.append(field(name, input));
    }
    const style = document.createElement("select");
    for (const choice of ["single", "double", "dashed"]) style.append(new Option(choice, choice, false, choice === layout.border.style));
    style.addEventListener("change", () => change({border_style: style.value}));
    props.append(field("border style", style));
    props.append(Object.assign(document.createElement("p"), {className: "muted",
      textContent: "Click an item on the page or in the list to edit it. Drag to move; drag the corner to resize."}));
  }

  stage.addEventListener("pointerdown", event => { if (event.target === stage || event.target === picture) select(undefined); });
  new ResizeObserver(() => { if (layout && !zoom) render(); }).observe(stage);
  await loadLayout();
}
