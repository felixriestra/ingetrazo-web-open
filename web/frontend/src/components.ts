/**
 * The Components section: a tree of user-owned categories (ported from 2DWM).
 *
 * Components sit in categories the user creates, renames, deletes, nests up to
 * three levels and hides; a component may be listed in several. A search box and
 * a "Show all categories" switch sit on top, and "In model" lists what the open
 * document already contains. Double-click (or Enter) arms a component for
 * placement; right-click manages categories; drag a component onto a category to
 * move it (hold Alt or Ctrl to list it there as well).
 *
 * The rules live on the server (`taxonomy.py`); this only draws the tree and
 * sends edits.
 */
import {responseApiError} from "./api";
import {askChoice, askText, confirmDialog, notice, showMenu} from "./dialogs";
import {requestTool} from "./library";

interface Entry {key: string; item: string; kind: "component" | "person"; name: string; tip: string; thumb: boolean; thumb_url: string; default_path: string[]}
interface Node {id: string; parent_id: string | null; name: string; hidden: boolean; hidden_effective: boolean; depth: number}
interface Taxonomy {max_depth: number; uncategorized: string; nodes: Node[]; items: Record<string, string[]>}

export interface ModelObject {id: string; name: string; kind: string}

export interface Components {
  /** The open document's top-level objects; the components among them are listed under "In model". */
  setInModel: (objects: ModelObject[]) => void;
}

const EXPANDED_KEY = "ingetrazo.components.expanded";
const SHOW_ALL_KEY = "ingetrazo.components.showAll";
const FOLDER = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h4l1.6 1.8H16.5A1.5 1.5 0 0 1 18 7.3v7.2a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 2 14.5z" fill="currentColor" opacity=".75"/></svg>';

function read(key: string): string {
  try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
}
function write(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* session only */ }
}

export function mountComponents(onSelectInModel: (ids: string[]) => void): Components {
  const panel = document.querySelector<HTMLElement>("#components-panel")!;
  let entries: Entry[] = [];
  let taxonomy: Taxonomy | undefined;
  let query = "";
  let showAll = read(SHOW_ALL_KEY) === "1";
  const expanded = new Set(read(EXPANDED_KEY).split(",").filter(Boolean));
  let modelObjects: ModelObject[] = [];

  const search = Object.assign(document.createElement("input"), {type: "search", placeholder: "Search components…"});
  search.className = "comp-search";
  search.setAttribute("aria-label", "Search components");
  const bar = document.createElement("div");
  bar.className = "comp-bar";
  const showAllLabel = document.createElement("label");
  const showAllBox = Object.assign(document.createElement("input"), {type: "checkbox", checked: showAll});
  showAllLabel.title = "Also list the categories you have hidden (right-click a category > Hide category)";
  showAllLabel.append(showAllBox, " Show all categories");
  const add = Object.assign(document.createElement("button"), {type: "button", textContent: "＋", title: "New category"});
  add.className = "comp-add";
  bar.append(showAllLabel, add);
  const tree = document.createElement("div");
  tree.className = "comp-tree";
  tree.setAttribute("role", "tree");
  tree.title = "Double-click a component to place it · right-click to manage categories · drag a component onto a category to move it (hold Alt or Ctrl to list it there as well)";
  const modelHeading = Object.assign(document.createElement("h3"), {textContent: "In model"});
  const modelList = document.createElement("div");
  modelList.className = "comp-model";
  panel.append(search, bar, tree, modelHeading, modelList);

  // --- server ---------------------------------------------------------------
  async function load(): Promise<void> {
    const [components, tax] = await Promise.all([
      fetch("/api/v1/library/components"), fetch("/api/v1/library/taxonomy")]);
    if (!components.ok || !tax.ok) return;
    entries = (await components.json() as {components: Entry[]}).components;
    taxonomy = await tax.json() as Taxonomy;
    render();
  }

  async function edit(operation: string, body: Record<string, unknown>): Promise<boolean> {
    const response = await fetch(`/api/v1/library/taxonomy/${operation}`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    if (!response.ok) {
      notice("Categories", (await responseApiError(response)).message);
      return false;
    }
    taxonomy = await response.json() as Taxonomy;
    render();
    return true;
  }

  // --- drawing --------------------------------------------------------------
  const children = (parent: string | null) => taxonomy!.nodes.filter(node => node.parent_id === parent);
  const placesOf = (entry: Entry) => taxonomy!.items[entry.item] ?? [];
  const nodeById = (id: string) => taxonomy!.nodes.find(node => node.id === id);

  function matches(entry: Entry): boolean {
    return !query || entry.name.toLowerCase().includes(query) || entry.tip.toLowerCase().includes(query);
  }

  function persistExpanded(): void { write(EXPANDED_KEY, [...expanded].sort().join(",")); }

  function render(): void {
    if (!taxonomy) return;
    tree.replaceChildren();
    const byNode = new Map<string, Entry[]>();
    for (const entry of entries.filter(matches)) {
      for (const id of placesOf(entry)) byNode.set(id, [...(byNode.get(id) ?? []), entry]);
    }

    /** Draw one level; returns the keys of every component at or under it. */
    const build = (parent: string | null, into: HTMLElement): Set<string> => {
      const found = new Set<string>();
      for (const node of children(parent)) {
        if (!showAll && node.hidden_effective) continue;
        const group = document.createElement("div");
        group.className = "comp-group";
        const row = document.createElement("div");
        row.className = "comp-row cat" + (node.hidden_effective ? " is-hidden" : "");
        row.dataset.cat = node.id;
        row.draggable = true;
        row.tabIndex = 0;
        row.setAttribute("role", "treeitem");
        const own = (byNode.get(node.id) ?? []).sort((a, b) => a.name.localeCompare(b.name));
        const body = document.createElement("div");
        body.className = "comp-children";
        for (const entry of own) body.append(itemRow(entry, node.id));
        const below = build(node.id, body);
        const count = new Set([...own.map(entry => entry.item), ...below]);
        if (query && count.size === 0) continue;
        const open = Boolean(query) || expanded.has(node.id);
        body.hidden = !open;
        row.setAttribute("aria-expanded", String(open));
        const arrow = Object.assign(document.createElement("span"), {className: "comp-arrow", textContent: open ? "▾" : "▸"});
        const icon = Object.assign(document.createElement("span"), {className: "comp-folder"});
        icon.innerHTML = FOLDER;
        const label = Object.assign(document.createElement("span"), {
          className: "comp-label",
          textContent: `${node.name}  (${count.size})${node.hidden_effective ? "  · hidden" : ""}`});
        row.append(arrow, icon, label);
        row.addEventListener("click", () => toggle(node.id));
        row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(node.id); } });
        row.addEventListener("contextmenu", event => { event.preventDefault(); event.stopPropagation(); categoryMenu(event.clientX, event.clientY, node); });
        wireDrag(row, "cat", node.id, parent);
        wireDrop(row, node.id);
        group.append(row, body);
        into.append(group);
        for (const key of count) found.add(key);
      }
      return found;
    };
    build(null, tree);
    if (!tree.childElementCount) {
      tree.append(Object.assign(document.createElement("p"), {className: "muted", textContent: query ? "No component matches." : "No categories yet. Use ＋ to add one."}));
    }
    renderInModel();
  }

  function toggle(id: string): void {
    if (expanded.has(id)) expanded.delete(id); else expanded.add(id);
    persistExpanded();
    render();
  }

  function itemRow(entry: Entry, parentId: string): HTMLElement {
    const row = document.createElement("div");
    row.className = "comp-row item";
    row.dataset.item = entry.item;
    row.draggable = true;
    row.tabIndex = 0;
    row.setAttribute("role", "treeitem");
    row.title = `${entry.name}: ${entry.tip}\nDouble-click to place it in the model.`;
    if (entry.thumb) {
      const image = Object.assign(document.createElement("img"), {src: entry.thumb_url, alt: "", loading: "lazy", width: 32, height: 32});
      row.append(image);
    }
    row.append(Object.assign(document.createElement("span"), {className: "comp-label", textContent: entry.name}));
    const insert = () => requestTool(entry.kind === "person" ? `place:person:${entry.key}` : `place:${entry.key}`);
    row.addEventListener("dblclick", insert);
    row.addEventListener("keydown", event => { if (event.key === "Enter") insert(); });
    row.addEventListener("click", event => { event.stopPropagation(); row.focus(); });
    row.addEventListener("contextmenu", event => { event.preventDefault(); event.stopPropagation(); itemMenu(event.clientX, event.clientY, entry, parentId, insert); });
    wireDrag(row, "item", entry.item, parentId);
    return row;
  }

  // --- drag and drop --------------------------------------------------------
  type Payload = {kind: "cat" | "item"; ref: string; origin: string | null};
  function wireDrag(row: HTMLElement, kind: "cat" | "item", ref: string, origin: string | null): void {
    row.addEventListener("dragstart", event => {
      event.stopPropagation();
      event.dataTransfer!.setData("application/x-ingetrazo-component", JSON.stringify({kind, ref, origin} satisfies Payload));
      event.dataTransfer!.effectAllowed = "copyMove";
    });
  }
  function wireDrop(target: HTMLElement, id: string | null): void {
    target.addEventListener("dragover", event => {
      if (!event.dataTransfer?.types.includes("application/x-ingetrazo-component")) return;
      event.preventDefault();
      event.stopPropagation();
      target.classList.add("drop-target");
    });
    target.addEventListener("dragleave", () => target.classList.remove("drop-target"));
    target.addEventListener("drop", event => {
      event.preventDefault();
      event.stopPropagation();
      target.classList.remove("drop-target");
      const raw = event.dataTransfer?.getData("application/x-ingetrazo-component");
      if (!raw) return;
      void dropped(JSON.parse(raw) as Payload, id, event.altKey || event.ctrlKey || event.metaKey);
    });
  }
  async function dropped(payload: Payload, target: string | null, copy: boolean): Promise<void> {
    if (payload.kind === "item") {
      if (target === null) return;
      if (copy || payload.origin === null) await edit("add", {item: payload.ref, node: target});
      else await edit("move_item", {item: payload.ref, from: payload.origin, to: target});
      expanded.add(target);
      persistExpanded();
      render();
    } else {
      await edit("move", {id: payload.ref, parent_id: target});
      if (target) { expanded.add(target); persistExpanded(); render(); }
    }
  }
  wireDrop(tree, null);   // empty space: a category dropped here becomes top-level

  // --- menus and prompts ----------------------------------------------------
  async function newCategory(parent: string | null): Promise<void> {
    const name = await askText(parent ? "New subcategory" : "New category", "Name:");
    if (name === null) return;
    if (await edit("create", {name, parent_id: parent}) && parent) { expanded.add(parent); persistExpanded(); render(); }
  }

  function categoryMenu(x: number, y: number, node: Node): void {
    showMenu(x, y, [
      {label: "New subcategory…", disabled: node.depth >= taxonomy!.max_depth, run: () => void newCategory(node.id)},
      {label: "Rename…", run: async () => {
        const name = await askText("Rename category", "Name:", node.name);
        if (name !== null) await edit("rename", {id: node.id, name});
      }},
      "-",
      {label: node.hidden ? "Show category" : "Hide category", run: () => void edit("hide", {id: node.id, hidden: !node.hidden})},
      "-",
      {label: "Delete…", run: async () => {
        const subs = taxonomy!.nodes.filter(other => isBelow(other, node.id)).length;
        const where = node.parent_id ? "their parent category" : `«${taxonomy!.uncategorized}»`;
        const extra = subs ? ` and its ${subs} subcategories` : "";
        if (await confirmDialog("Delete category", `Delete «${node.name}»${extra}?\n\nThe components inside are not deleted. They move to ${where}.`)) {
          expanded.delete(node.id);
          await edit("delete", {id: node.id});
        }
      }},
      "-",
      {label: "New category…", run: () => void newCategory(null)},
    ]);
  }

  function isBelow(node: Node, ancestor: string): boolean {
    for (let current = node.parent_id; current; current = nodeById(current)?.parent_id ?? null) {
      if (current === ancestor) return true;
    }
    return false;
  }

  async function pickCategory(entry: Entry, title: string): Promise<string | null> {
    const taken = new Set(placesOf(entry));
    const path = (node: Node): string => node.parent_id ? `${path(nodeById(node.parent_id)!)} > ${node.name}` : node.name;
    const choices = taxonomy!.nodes.filter(node => !taken.has(node.id))
      .map(node => [node.id, path(node)] as [string, string]).sort((a, b) => a[1].localeCompare(b[1]));
    if (!choices.length) { notice(title, "It is already in every category."); return null; }
    return askChoice(title, "Category:", choices);
  }

  function itemMenu(x: number, y: number, entry: Entry, here: string, insert: () => void): void {
    const here_name = nodeById(here)?.name ?? "";
    showMenu(x, y, [
      {label: "Place in the model", run: insert},
      "-",
      {label: "Also list in another category…", run: async () => {
        const node = await pickCategory(entry, "Also list in category");
        if (node) { await edit("add", {item: entry.item, node}); expanded.add(node); persistExpanded(); render(); }
      }},
      {label: "Move to another category…", run: async () => {
        const node = await pickCategory(entry, "Move to category");
        if (node) { await edit("move_item", {item: entry.item, from: here, to: node}); expanded.add(node); persistExpanded(); render(); }
      }},
      {label: `Remove from «${here_name}»`, disabled: placesOf(entry).length < 2, run: () => void edit("remove", {item: entry.item, node: here})},
    ]);
  }

  // --- controls -------------------------------------------------------------
  search.addEventListener("input", () => { query = search.value.trim().toLowerCase(); render(); });
  showAllBox.addEventListener("change", () => { showAll = showAllBox.checked; write(SHOW_ALL_KEY, showAll ? "1" : "0"); render(); });
  add.addEventListener("click", () => void newCategory(null));
  tree.addEventListener("contextmenu", event => {
    event.preventDefault();
    showMenu(event.clientX, event.clientY, [{label: "New category…", run: () => void newCategory(null)}]);
  });

  // --- in model -------------------------------------------------------------
  /** Components: real component instances, or objects named after a library component. */
  function inModelRows(): {name: string; ids: string[]}[] {
    const known = new Set(entries.map(entry => entry.name.toLowerCase()));
    const byName = new Map<string, string[]>();
    for (const object of modelObjects) {
      if (object.kind !== "component" && !known.has(object.name.toLowerCase())) continue;
      byName.set(object.name, [...(byName.get(object.name) ?? []), object.id]);
    }
    return [...byName].map(([name, ids]) => ({name, ids}))
      .sort((a, b) => b.ids.length - a.ids.length || a.name.localeCompare(b.name));
  }

  function renderInModel(): void {
    modelList.replaceChildren();
    const rows = inModelRows();
    if (!rows.length) {
      modelList.append(Object.assign(document.createElement("p"), {className: "muted", textContent: "No components yet"}));
      return;
    }
    for (const row of rows) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "comp-model-row";
      button.title = "Click to select its copies";
      button.textContent = `${row.name}  (${row.ids.length}×)`;
      button.addEventListener("click", () => onSelectInModel(row.ids));
      modelList.append(button);
    }
  }

  void load();
  return {
    setInModel(objects) { modelObjects = objects; renderInModel(); },
  };
}
