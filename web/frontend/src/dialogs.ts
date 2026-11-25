/** Small modal dialogs: ask for text, pick from a list, confirm, or show a message. */

function open(build: (dialog: HTMLDialogElement, close: () => void) => void): void {
  const dialog = document.createElement("dialog");
  dialog.className = "shortcut-dialog";
  const close = () => { if (dialog.open) dialog.close(); };
  dialog.addEventListener("close", () => dialog.remove());
  build(dialog, close);
  document.body.append(dialog);
  dialog.showModal();
}

function buttons(close: () => void, submitLabel: string, onSubmit?: () => void) {
  const row = document.createElement("div");
  row.className = "dialog-buttons";
  const cancel = Object.assign(document.createElement("button"), {type: "button", textContent: "Cancel"});
  cancel.addEventListener("click", close);
  const ok = Object.assign(document.createElement("button"), {type: onSubmit ? "button" : "submit", textContent: submitLabel});
  if (onSubmit) ok.addEventListener("click", onSubmit);
  row.append(cancel, ok);
  return {row, ok, cancel};
}

/** Ask for a line of text; resolves ``null`` when cancelled or left empty. */
export function askText(title: string, label: string, initial = ""): Promise<string | null> {
  return new Promise(resolve => {
    let answer: string | null = null;
    open((dialog, close) => {
      const form = document.createElement("form");
      form.method = "dialog";
      const heading = Object.assign(document.createElement("h2"), {textContent: title});
      const caption = document.createElement("label");
      caption.textContent = `${label} `;
      const input = Object.assign(document.createElement("input"), {type: "text", value: initial, maxLength: 4000});
      caption.append(input);
      form.append(heading, caption, buttons(close, "OK").row);
      form.addEventListener("submit", () => { answer = input.value.trim() || null; });
      dialog.append(form);
      dialog.addEventListener("close", () => resolve(answer));
      queueMicrotask(() => { input.focus(); input.select(); });
    });
  });
}

/** Pick one of ``choices`` ([value, label]); resolves the value or ``null``. */
export function askChoice(title: string, label: string, choices: [string, string][]): Promise<string | null> {
  return new Promise(resolve => {
    let answer: string | null = null;
    open((dialog, close) => {
      const form = document.createElement("form");
      form.method = "dialog";
      const heading = Object.assign(document.createElement("h2"), {textContent: title});
      const caption = document.createElement("label");
      caption.textContent = `${label} `;
      const select = document.createElement("select");
      for (const [value, text] of choices) select.append(new Option(text, value));
      caption.append(select);
      form.append(heading, caption, buttons(close, "OK").row);
      form.addEventListener("submit", () => { answer = select.value; });
      dialog.append(form);
      dialog.addEventListener("close", () => resolve(answer));
    });
  });
}

/** Ask a yes/no question. */
export function confirmDialog(title: string, message: string, yes = "Delete"): Promise<boolean> {
  return new Promise(resolve => {
    let answer = false;
    open((dialog, close) => {
      const heading = Object.assign(document.createElement("h2"), {textContent: title});
      const text = Object.assign(document.createElement("p"), {textContent: message});
      text.style.whiteSpace = "pre-line";
      const {row} = buttons(close, yes, () => { answer = true; close(); });
      dialog.append(heading, text, row);
      dialog.addEventListener("close", () => resolve(answer));
    });
  });
}

/** Show a message with an OK button. */
export function notice(title: string, message: string): void {
  open((dialog, close) => {
    const heading = Object.assign(document.createElement("h2"), {textContent: title});
    const text = Object.assign(document.createElement("p"), {textContent: message});
    const ok = Object.assign(document.createElement("button"), {type: "button", textContent: "OK"});
    ok.addEventListener("click", close);
    dialog.append(heading, text, ok);
  });
}

/** A floating context menu at a point; closes on any outside click or Escape. */
export function showMenu(x: number, y: number, items: ({label: string; run: () => void; disabled?: boolean} | "-")[]): void {
  document.querySelectorAll(".context-menu").forEach(node => node.remove());
  const panel = document.createElement("div");
  panel.className = "menu-panel context-menu";
  panel.setAttribute("role", "menu");
  const close = () => { panel.remove(); document.removeEventListener("click", close, true); document.removeEventListener("keydown", onKey, true); };
  const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
  for (const item of items) {
    if (item === "-") { panel.append(document.createElement("hr")); continue; }
    const entry = document.createElement("button");
    entry.type = "button";
    entry.className = "menu-item";
    entry.style.gridTemplateColumns = "1fr";
    entry.setAttribute("role", "menuitem");
    entry.disabled = Boolean(item.disabled);
    entry.textContent = item.label;
    entry.addEventListener("click", () => { close(); item.run(); });
    panel.append(entry);
  }
  document.body.append(panel);
  panel.style.left = `${Math.min(x, window.innerWidth - 250)}px`;
  panel.style.top = `${Math.min(y, window.innerHeight - items.length * 28 - 16)}px`;
  setTimeout(() => { document.addEventListener("click", close, true); document.addEventListener("keydown", onKey, true); }, 0);
}
