/**
 * Draggable and floatable toolbars.
 *
 * Grab a toolbar by its grip: drop it on the top bar or the left column to dock it
 * there (in the position you drop it), or anywhere else to leave it floating over the
 * model. Double-click the grip to send it back to where the desktop puts it. The layout
 * is remembered in this browser.
 */
const STORAGE = "ingetrazo.toolbars";

type Place = {mode: "top" | "left"; order: number} | {mode: "float"; x: number; y: number};

interface Home {group: HTMLElement; parent: HTMLElement; index: number}

export interface ToolbarDocking {
  reset: () => void;
}

export function mountToolbarDocking(): ToolbarDocking {
  const top = document.querySelector<HTMLElement>("#toolbars")!;
  const left = document.querySelector<HTMLElement>("#toolbars-left")!;
  const groups = [...document.querySelectorAll<HTMLElement>(".toolbar-group")];
  const homes: Home[] = groups.map(group => ({group, parent: group.parentElement!, index: [...group.parentElement!.children].indexOf(group)}));
  const homeOf = (group: HTMLElement) => homes.find(home => home.group === group)!;
  const defaultVertical = new Map(groups.map(group => [group, group.classList.contains("vertical")]));

  function dock(group: HTMLElement, where: "top" | "left", beforeNode: Element | null): void {
    group.classList.remove("floating");
    group.style.left = group.style.top = "";
    group.classList.toggle("vertical", where === "left");
    (where === "left" ? left : top).insertBefore(group, beforeNode);
  }

  function float(group: HTMLElement, x: number, y: number): void {
    group.classList.add("floating");
    group.classList.remove("vertical");
    document.body.append(group);
    const width = group.offsetWidth;
    const height = group.offsetHeight;
    group.style.left = `${Math.max(0, Math.min(window.innerWidth - width, x))}px`;
    group.style.top = `${Math.max(0, Math.min(window.innerHeight - height, y))}px`;
  }

  function save(): void {
    const layout: Record<string, Place> = {};
    for (const group of groups) {
      const id = group.dataset.toolbar!;
      if (group.classList.contains("floating")) layout[id] = {mode: "float", x: group.offsetLeft, y: group.offsetTop};
      else {
        const parent = group.parentElement === left ? left : top;
        layout[id] = {mode: parent === left ? "left" : "top", order: [...parent.children].indexOf(group)};
      }
    }
    try { localStorage.setItem(STORAGE, JSON.stringify(layout)); } catch { /* session only */ }
  }

  function resetOne(group: HTMLElement): void {
    const home = homeOf(group);
    group.classList.remove("floating");
    group.style.left = group.style.top = "";
    group.classList.toggle("vertical", defaultVertical.get(group) === true);
    const sibling = [...home.parent.children].filter(node => node !== group)[home.index] ?? null;
    home.parent.insertBefore(group, sibling);
  }

  function reset(): void {
    for (const home of [...homes].sort((a, b) => a.index - b.index)) resetOne(home.group);
    try { localStorage.removeItem(STORAGE); } catch { /* nothing to forget */ }
  }

  // Restore the remembered layout.
  try {
    const layout = JSON.parse(localStorage.getItem(STORAGE) ?? "{}") as Record<string, Place>;
    const docked = groups
      .filter(group => layout[group.dataset.toolbar!] && layout[group.dataset.toolbar!].mode !== "float")
      .sort((a, b) => (layout[a.dataset.toolbar!] as {order: number}).order - (layout[b.dataset.toolbar!] as {order: number}).order);
    for (const group of docked) dock(group, layout[group.dataset.toolbar!].mode as "top" | "left", null);
    for (const group of groups) {
      const place = layout[group.dataset.toolbar!];
      if (place?.mode === "float") float(group, Number(place.x) || 0, Number(place.y) || 0);
    }
  } catch { /* defaults */ }

  const inside = (box: HTMLElement, x: number, y: number, slack = 18) => {
    const rect = box.getBoundingClientRect();
    return x >= rect.left - slack && x <= rect.right + slack && y >= rect.top - slack && y <= rect.bottom + slack;
  };

  for (const group of groups) {
    const grip = group.querySelector<HTMLElement>(".toolbar-grip");
    if (!grip) continue;
    grip.title = "Drag to move or float this toolbar · double-click to put it back";
    grip.addEventListener("dblclick", () => { resetOne(group); save(); });
    grip.addEventListener("pointerdown", down => {
      if (down.button !== 0) return;
      down.preventDefault();
      const start = {x: down.clientX, y: down.clientY};
      const rect = group.getBoundingClientRect();
      const offset = {x: down.clientX - rect.left, y: down.clientY - rect.top};
      let dragging = false;

      const onMove = (event: PointerEvent) => {
        if (!dragging && Math.hypot(event.clientX - start.x, event.clientY - start.y) < 5) return;
        if (!dragging) { dragging = true; float(group, rect.left, rect.top); group.classList.add("dragging"); grip.setPointerCapture(down.pointerId); }
        group.style.left = `${event.clientX - offset.x}px`;
        group.style.top = `${event.clientY - offset.y}px`;
        top.classList.toggle("drop-target", inside(top, event.clientX, event.clientY));
        left.classList.toggle("drop-target", !top.classList.contains("drop-target") && inside(left, event.clientX, event.clientY));
      };
      const onUp = (event: PointerEvent) => {
        if (grip.hasPointerCapture(down.pointerId)) grip.releasePointerCapture(down.pointerId);
        grip.removeEventListener("pointermove", onMove);
        grip.removeEventListener("pointerup", onUp);
        grip.removeEventListener("pointercancel", onUp);
        top.classList.remove("drop-target");
        left.classList.remove("drop-target");
        if (!dragging) return;
        group.classList.remove("dragging");
        if (inside(top, event.clientX, event.clientY)) {
          const others = [...top.children].filter(node => node !== group);
          dock(group, "top", others.find(node => event.clientX < node.getBoundingClientRect().left + node.getBoundingClientRect().width / 2) ?? null);
        } else if (inside(left, event.clientX, event.clientY)) {
          const others = [...left.children].filter(node => node !== group);
          dock(group, "left", others.find(node => event.clientY < node.getBoundingClientRect().top + node.getBoundingClientRect().height / 2) ?? null);
        }
        save();
      };
      grip.addEventListener("pointermove", onMove);
      grip.addEventListener("pointerup", onUp);
      grip.addEventListener("pointercancel", onUp);
    });
  }

  window.addEventListener("resize", () => {
    for (const group of groups.filter(item => item.classList.contains("floating"))) {
      group.style.left = `${Math.max(0, Math.min(window.innerWidth - group.offsetWidth, group.offsetLeft))}px`;
      group.style.top = `${Math.max(0, Math.min(window.innerHeight - group.offsetHeight, group.offsetTop))}px`;
    }
  });
  return {reset};
}
