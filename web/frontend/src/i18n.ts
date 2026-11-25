/**
 * Localisation with the desktop's own translation catalogues.
 *
 * The server serves ``i18n/<code>.json`` (English source text → translation). The
 * interface is written in English; this swaps in the translation of every text node
 * and every title/placeholder/aria-label whose English text is in the catalogue, and
 * keeps doing so for what the application adds later (a MutationObserver), so no
 * string in the code needs wrapping. Text with no translation stays English, and
 * choosing English puts every original back. The choice is remembered per browser.
 */
const STORAGE = "ingetrazo.language";
const ATTRIBUTES = ["title", "placeholder", "aria-label"] as const;

interface Language {code: string; name: string}

let catalogue: Record<string, string> = {};
let language = "en";
let languages: Language[] = [{code: "en", name: "English"}];

// What each node showed in English, and what we last wrote into it.
const textState = new WeakMap<Node, {source: string; shown: string}>();
const attributeState = new WeakMap<Element, Map<string, {source: string; shown: string}>>();
const listeners: (() => void)[] = [];
let observer: MutationObserver | undefined;

function translated(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return text;
  const hit = catalogue[trimmed];
  return hit === undefined ? text : text.replace(trimmed, hit);
}

function translateTextNode(node: Text): void {
  const state = textState.get(node);
  // The application rewrote the text since we last touched it: that is the new English.
  const source = state && node.data === state.shown ? state.source : node.data;
  const shown = translated(source);
  textState.set(node, {source, shown});
  if (node.data !== shown) node.data = shown;
  const parent = node.parentElement;
  if (parent && parent.childNodes.length === 1) parent.dataset.i18nSource = source.trim();   // code that reads labels can still match them
}

function translateAttributes(element: Element): void {
  for (const name of ATTRIBUTES) {
    const value = element.getAttribute(name);
    if (value === null) continue;
    const states = attributeState.get(element) ?? new Map();
    attributeState.set(element, states);
    const state = states.get(name);
    const source = state && value === state.shown ? state.source : value;
    const shown = translated(source);
    states.set(name, {source, shown});
    if (value !== shown) element.setAttribute(name, shown);
  }
}

function translateTree(root: Node): void {
  if (root.nodeType === Node.TEXT_NODE) { translateTextNode(root as Text); return; }
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  if (root instanceof Element) {
    if (/^(SCRIPT|STYLE|TEXTAREA)$/.test(root.tagName)) return;
    translateAttributes(root);
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node instanceof Text) {
      if (!/^(SCRIPT|STYLE|TEXTAREA)$/.test(node.parentElement?.tagName ?? "")) translateTextNode(node);
    } else translateAttributes(node as Element);
  }
}

function observe(): void {
  observer ??= new MutationObserver(records => {
    for (const record of records) {
      if (record.type === "childList") record.addedNodes.forEach(translateTree);
      else if (record.type === "characterData") translateTextNode(record.target as Text);
      else if (record.type === "attributes") translateAttributes(record.target as Element);
    }
  });
  observer.observe(document.body, {subtree: true, childList: true, characterData: true,
    attributes: true, attributeFilter: [...ATTRIBUTES]});
}

/** Translate one string in code (for text built at run time). */
export function tr(text: string): string {
  return catalogue[text] ?? text;
}

export const currentLanguage = () => language;
export const availableLanguages = () => languages;
export const onLanguageChange = (listener: () => void) => { listeners.push(listener); };

export async function setLanguage(code: string): Promise<void> {
  let next: Record<string, string> = {};
  if (code !== "en") {
    try {
      const response = await fetch(`/api/v1/i18n/${encodeURIComponent(code)}`);
      if (!response.ok) throw new Error(String(response.status));
      next = await response.json() as Record<string, string>;
    } catch { code = "en"; }
  }
  catalogue = next;
  language = code;
  document.documentElement.lang = code;
  try { localStorage.setItem(STORAGE, code); } catch { /* session only */ }
  observer?.disconnect();
  translateTree(document.body);          // re-derive every node from its English original
  observe();
  for (const listener of listeners) listener();
}

/** Load the language list and apply the remembered language (English by default). */
export async function initLanguage(): Promise<void> {
  try {
    const response = await fetch("/api/v1/i18n");
    if (response.ok) languages = (await response.json() as {languages: Language[]}).languages;
  } catch { /* English only */ }
  let remembered = "en";
  try { remembered = localStorage.getItem(STORAGE) || "en"; } catch { /* default */ }
  if (!languages.some(item => item.code === remembered)) remembered = "en";
  await setLanguage(remembered);
}
