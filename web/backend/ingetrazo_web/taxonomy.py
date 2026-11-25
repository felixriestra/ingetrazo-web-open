"""The Components tray's category tree: which folder each component sits in.

Ported from 2DWM's ``parametric/catalog/taxonomy.py`` with the same rules; only
the storage differs (one JSON file next to the documents instead of a SQLite
catalog).

A library past a few dozen entries turns a flat list into an endless scroll, so
components are grouped in categories the user owns: created, renamed, deleted,
nested up to :data:`MAX_DEPTH` levels (``Furniture > Living room``) and hidden.
A component may be listed in several categories. An item nobody touched has no
record of its own: it sits where its default path says, if that category still
exists, and otherwise in ``Uncategorized`` - so a component that arrives in a
later release never vanishes, and a category the user deleted never comes back
by itself. The first edit to an item writes its current places down first, so
adding a second category never loses the default one.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

#: Top level + two sublevels: "furniture > living room > floor standing".
MAX_DEPTH = 3
UNCATEGORIZED = "Uncategorized"

#: The tree a fresh install starts with. A category name is something the user
#: edits, so it is stored as written, never translated on the way out.
DEFAULT_TREE: tuple = (
    ("Furniture", (("Living room", ()),)),
    ("Outdoor", (("Plants", ()),)),
    ("People", ()),
    ("Vehicles", ()),
)

#: Where the components that ship with the app start out, by item key.
DEFAULT_PATHS: dict = {
    "component:sofa": ("Furniture", "Living room"),
    "component:banco": ("Outdoor",),
    "component:fuente": ("Outdoor",),
    "component:arbol": ("Outdoor", "Plants"),
    "component:abedul": ("Outdoor", "Plants"),
    "component:chica": ("People",),
    "component:pickup": ("Vehicles",),
    "component:suv": ("Vehicles",),
}


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    name: str
    hidden: bool


class TaxonomyError(ValueError):
    """A category edit the rules refuse; the message is fit to show."""


def _clean(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise TaxonomyError("A category needs a name.")
    if len(name) > 80:
        raise TaxonomyError("A category name is at most 80 characters.")
    return name


class Taxonomy:
    """The category tree, persisted as JSON."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = RLock()
        self._nodes: dict[str, dict] = {}
        self._items: dict[str, list[str]] = {}
        self._seeded = False
        self._load()
        with self._lock:
            if not self._seeded:
                self._seed_defaults()

    # ---- persistence -----------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._nodes = {n["id"]: n for n in raw.get("nodes", [])
                       if isinstance(n, dict) and "id" in n}
        self._items = {k: [i for i in v if i in self._nodes]
                       for k, v in raw.get("items", {}).items()}
        self._seeded = bool(raw.get("seeded"))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seeded": self._seeded, "nodes": list(self._nodes.values()),
                   "items": self._items}
        fd, name = tempfile.mkstemp(dir=self._path.parent, prefix="taxonomy-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=1)
            os.replace(name, self._path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    # ---- reading ---------------------------------------------------------------

    def nodes(self) -> list[Node]:
        out = [Node(n["id"], n.get("parent_id"), n["name"], bool(n.get("hidden")))
               for n in self._nodes.values()]
        out.sort(key=lambda n: n.name.casefold())
        return out

    def get(self, node_id: str | None) -> Node | None:
        n = self._nodes.get(node_id) if node_id else None
        return Node(n["id"], n.get("parent_id"), n["name"], bool(n.get("hidden"))) if n else None

    def children(self, parent_id: str | None) -> list[Node]:
        return [n for n in self.nodes() if n.parent_id == parent_id]

    def depth(self, node_id: str) -> int:
        """1 for a top-level category."""
        d, node = 0, self.get(node_id)
        while node is not None:
            d += 1
            node = self.get(node.parent_id)
        return d

    def path(self, node_id: str) -> tuple:
        names, node = [], self.get(node_id)
        while node is not None:
            names.append(node.name)
            node = self.get(node.parent_id)
        return tuple(reversed(names))

    def descendants(self, node_id: str) -> list[str]:
        by_parent: dict = {}
        for n in self.nodes():
            by_parent.setdefault(n.parent_id, []).append(n.id)
        out, stack = [], list(by_parent.get(node_id, ()))
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(by_parent.get(cur, ()))
        return out

    def height(self, node_id: str) -> int:
        """Levels in the subtree rooted at ``node_id`` (a leaf is 1)."""
        return 1 + max((self.height(k.id) for k in self.children(node_id)), default=0)

    def is_hidden(self, node_id: str) -> bool:
        """Hidden itself, or inside a hidden category."""
        node = self.get(node_id)
        while node is not None:
            if node.hidden:
                return True
            node = self.get(node.parent_id)
        return False

    def find(self, path: tuple) -> Node | None:
        """The category at this name path, matching names case-insensitively."""
        parent, node = None, None
        for name in path:
            node = next((n for n in self.children(parent)
                         if n.name.casefold() == name.casefold()), None)
            if node is None:
                return None
            parent = node.id
        return node

    def _default_node(self, item_key: str, default_path: tuple) -> Node:
        if not default_path:
            default_path = DEFAULT_PATHS.get(item_key, ())
        if default_path:
            node = self.find(tuple(default_path))
            if node is not None:
                return node
        return self._ensure_uncategorized()

    def _explicit(self, item_key: str) -> list[Node]:
        nodes = [self.get(i) for i in self._items.get(item_key, [])]
        return [n for n in nodes if n is not None]

    def nodes_of(self, item_key: str, default_path: tuple = ()) -> list[Node]:
        """Every category an item is listed in (never empty)."""
        with self._lock:
            nodes = self._explicit(item_key)
            if nodes:
                nodes.sort(key=lambda n: self.path(n.id))
                return nodes
            return [self._default_node(item_key, default_path)]

    def choices(self, exclude: str | None = None, max_depth: int = MAX_DEPTH) -> list:
        """``[(id, "Furniture > Living room")]`` in tree order."""
        skip = {exclude, *self.descendants(exclude)} if exclude else set()
        out: list = []

        def walk(parent):
            for n in self.children(parent):
                if n.id in skip:
                    continue
                if self.depth(n.id) <= max_depth:
                    out.append((n.id, " > ".join(self.path(n.id))))
                walk(n.id)
        walk(None)
        return out

    # ---- editing ---------------------------------------------------------------

    def _check_name(self, name: str, parent_id: str | None, self_id: str | None = None) -> str:
        name = _clean(name)
        for sib in self.children(parent_id):
            if sib.id != self_id and sib.name.casefold() == name.casefold():
                raise TaxonomyError(f"«{name}» already exists here.")
        return name

    def create(self, name: str, parent_id: str | None = None) -> Node:
        with self._lock:
            if parent_id is not None:
                if self.get(parent_id) is None:
                    raise TaxonomyError("That category no longer exists.")
                if self.depth(parent_id) + 1 > MAX_DEPTH:
                    raise TaxonomyError(f"Categories nest at most {MAX_DEPTH} levels deep.")
            name = self._check_name(name, parent_id)
            node_id = uuid.uuid4().hex
            self._nodes[node_id] = {"id": node_id, "parent_id": parent_id, "name": name, "hidden": False}
            self._save()
            return self.get(node_id)

    def rename(self, node_id: str, name: str) -> Node:
        with self._lock:
            node = self.get(node_id)
            if node is None:
                raise TaxonomyError("That category no longer exists.")
            self._nodes[node_id]["name"] = self._check_name(name, node.parent_id, node_id)
            self._save()
            return self.get(node_id)

    def set_hidden(self, node_id: str, hidden: bool) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id]["hidden"] = bool(hidden)
                self._save()

    def move(self, node_id: str, new_parent_id: str | None) -> Node:
        """Re-parent a category (``None`` = top level), keeping its subtree and
        the limit of :data:`MAX_DEPTH` levels."""
        with self._lock:
            node = self.get(node_id)
            if node is None:
                raise TaxonomyError("That category no longer exists.")
            if new_parent_id == node.parent_id:
                return node
            if new_parent_id is not None:
                if self.get(new_parent_id) is None:
                    raise TaxonomyError("That category no longer exists.")
                if new_parent_id == node_id or new_parent_id in self.descendants(node_id):
                    raise TaxonomyError("A category cannot be moved inside itself.")
                base = self.depth(new_parent_id)
            else:
                base = 0
            if base + self.height(node_id) > MAX_DEPTH:
                raise TaxonomyError(f"Categories nest at most {MAX_DEPTH} levels deep.")
            self._check_name(node.name, new_parent_id, node_id)
            self._nodes[node_id]["parent_id"] = new_parent_id
            self._save()
            return self.get(node_id)

    def delete(self, node_id: str) -> None:
        """Delete a category and the categories inside it. Components are never
        lost: one listed ONLY there moves up to the parent (or to
        ``Uncategorized`` from the top level); one listed elsewhere simply stops
        being listed here."""
        with self._lock:
            node = self.get(node_id)
            if node is None:
                return
            doomed = {node_id, *self.descendants(node_id)}
            if node.parent_id is not None:
                target = node.parent_id
            elif node.name.casefold() == UNCATEGORIZED.casefold():
                target = None           # its items fall back to where they began
            else:
                target = self._ensure_uncategorized().id
            stranded = []
            if target is not None:
                for key, ids in self._items.items():
                    if any(i in doomed for i in ids) and not any(i not in doomed for i in ids):
                        stranded.append(key)
            for key in list(self._items):
                self._items[key] = [i for i in self._items[key] if i not in doomed]
                if not self._items[key]:
                    del self._items[key]
            for doomed_id in doomed:
                self._nodes.pop(doomed_id, None)
            for key in stranded:
                self._items.setdefault(key, []).append(target)
            self._save()

    # ---- which categories an item is in ----------------------------------------

    def _materialize(self, item_key: str, default_path: tuple) -> None:
        """Write an untouched item's current places down, so an edit adds to
        them instead of replacing them. ``Uncategorized`` is left out: for an
        item nobody filed it only means "no place yet"."""
        if self._explicit(item_key):
            return
        for n in self.nodes_of(item_key, default_path):
            if n.parent_id is None and n.name.casefold() == UNCATEGORIZED.casefold():
                continue
            self._items.setdefault(item_key, []).append(n.id)

    def _require(self, node_id: str) -> None:
        if self.get(node_id) is None:
            raise TaxonomyError("That category no longer exists.")

    def add_to(self, item_key: str, node_id: str, default_path: tuple = ()) -> None:
        """List the item in one more category (keeping the others)."""
        with self._lock:
            self._require(node_id)
            self._materialize(item_key, default_path)
            ids = self._items.setdefault(item_key, [])
            if node_id not in ids:
                ids.append(node_id)
            self._save()

    def remove_from(self, item_key: str, node_id: str, default_path: tuple = ()) -> None:
        """Stop listing the item in one category. Its last category cannot be
        taken away: it goes to ``Uncategorized`` instead."""
        with self._lock:
            self._materialize(item_key, default_path)
            self._items[item_key] = [i for i in self._items.get(item_key, []) if i != node_id]
            if not self._explicit(item_key):
                self._items[item_key] = [self._ensure_uncategorized().id]
            self._save()

    def move_item(self, item_key: str, from_id: str, to_id: str, default_path: tuple = ()) -> None:
        """Take the item out of ``from_id`` and list it in ``to_id``."""
        with self._lock:
            self._require(to_id)
            if from_id == to_id:
                return
            self._materialize(item_key, default_path)
            ids = [i for i in self._items.get(item_key, []) if i != from_id]
            if to_id not in ids:
                ids.append(to_id)
            self._items[item_key] = ids
            self._save()

    # ---- internals -------------------------------------------------------------

    def _ensure_uncategorized(self) -> Node:
        for n in self.children(None):
            if n.name.casefold() == UNCATEGORIZED.casefold():
                return n
        node_id = uuid.uuid4().hex
        self._nodes[node_id] = {"id": node_id, "parent_id": None, "name": UNCATEGORIZED, "hidden": False}
        self._save()
        return self.get(node_id)

    def _seed_defaults(self) -> None:
        """Once per install: lay down the starting tree. After that the tree is
        the user's; a deleted default never reappears."""
        self._seeded = True

        def build(entries, parent):
            for name, kids in entries:
                node_id = uuid.uuid4().hex
                self._nodes[node_id] = {"id": node_id, "parent_id": parent, "name": name, "hidden": False}
                build(kids, node_id)
        build(DEFAULT_TREE, None)
        self._save()
