"""The Components category tree (ported from 2DWM's rules) and its HTTP surface."""
import pytest

from web.backend.ingetrazo_web.taxonomy import (
    DEFAULT_PATHS, MAX_DEPTH, UNCATEGORIZED, Taxonomy, TaxonomyError)


@pytest.fixture
def tax(tmp_path):
    return Taxonomy(tmp_path / "taxonomy.json")


def names(tax, parent=None):
    return [n.name for n in tax.children(parent)]


def listed(tax, key, default=()):
    return sorted(n.name for n in tax.nodes_of(key, default))


def test_a_fresh_install_starts_with_the_default_tree_once(tmp_path):
    first = Taxonomy(tmp_path / "t.json")
    assert "Furniture" in names(first)
    assert names(first, first.find(("Furniture",)).id) == ["Living room"]
    first.delete(first.find(("Vehicles",)).id)
    assert "Vehicles" not in names(Taxonomy(tmp_path / "t.json"))     # a deleted default stays deleted


def test_every_shipped_default_path_exists(tax):
    for path in DEFAULT_PATHS.values():
        assert tax.find(path) is not None, path


def test_nesting_stops_at_three_levels(tax):
    low = tax.create("Screws", tax.create("Fasteners", tax.create("Hardware").id).id)
    assert tax.depth(low.id) == MAX_DEPTH == 3
    with pytest.raises(TaxonomyError):
        tax.create("Too deep", low.id)


def test_sibling_names_are_unique_ignoring_case_and_spaces(tax):
    tax.create("Lighting")
    with pytest.raises(TaxonomyError):
        tax.create("  lighting ")
    other = tax.create("Lamps")
    with pytest.raises(TaxonomyError):
        tax.rename(other.id, "LIGHTING")
    with pytest.raises(TaxonomyError):
        tax.create("   ")
    a, b = tax.create("A"), tax.create("B")
    tax.create("Shared", a.id)
    tax.create("Shared", b.id)


def test_move_respects_depth_cycles_and_name_clashes(tax):
    a = tax.create("A")
    b = tax.create("B", a.id)
    c = tax.create("C", b.id)
    for bad in (c.id, a.id):
        with pytest.raises(TaxonomyError):
            tax.move(a.id, bad)
    d1 = tax.create("D1", tax.create("D").id)
    with pytest.raises(TaxonomyError):
        tax.move(a.id, d1.id)
    tax.move(c.id, None)
    assert tax.depth(c.id) == 1
    tax.create("Plants", a.id)
    clash = tax.create("Plants")
    with pytest.raises(TaxonomyError):
        tax.move(clash.id, a.id)


def test_hiding_a_category_hides_what_is_inside_it(tax):
    top = tax.create("Hardware")
    sub = tax.create("Bearings", top.id)
    tax.set_hidden(top.id, True)
    assert tax.is_hidden(top.id) and tax.is_hidden(sub.id)
    assert not tax.is_hidden(tax.find(("Furniture",)).id)
    tax.set_hidden(top.id, False)
    assert not tax.is_hidden(sub.id)


def test_an_unmoved_item_follows_its_default_then_uncategorized(tax):
    key = "component:sofa"
    assert listed(tax, key) == ["Living room"]
    tax.delete(tax.find(("Furniture", "Living room")).id)
    assert listed(tax, key) == [UNCATEGORIZED]
    assert listed(tax, "component:never.heard.of") == [UNCATEGORIZED]


def test_an_item_can_be_listed_in_several_categories(tax):
    key = "component:sofa"
    outdoor = tax.find(("Outdoor",))
    tax.add_to(key, outdoor.id)
    assert listed(tax, key) == ["Living room", "Outdoor"]          # the default place is kept
    tax.remove_from(key, tax.find(("Furniture", "Living room")).id)
    assert listed(tax, key) == ["Outdoor"]
    tax.remove_from(key, outdoor.id)
    assert listed(tax, key) == [UNCATEGORIZED]                      # never unreachable


def test_move_item_and_delete_never_lose_components(tax):
    key = "component:banco"
    garden = tax.create("Garden")
    tax.move_item(key, tax.find(("Outdoor",)).id, garden.id)
    assert listed(tax, key) == ["Garden"]
    nested = tax.create("Seats", garden.id)
    tax.add_to(key, nested.id)
    tax.remove_from(key, garden.id)
    tax.delete(nested.id)                                           # stranded: moves up to the parent
    assert listed(tax, key) == ["Garden"]
    tax.delete(garden.id)
    assert listed(tax, key) == [UNCATEGORIZED]


def test_the_tree_survives_a_restart(tmp_path):
    first = Taxonomy(tmp_path / "t.json")
    mine = first.create("Mine")
    first.add_to("component:sofa", mine.id)
    again = Taxonomy(tmp_path / "t.json")
    assert again.find(("Mine",)) is not None
    assert listed(again, "component:sofa") == ["Living room", "Mine"]


def test_http_surface(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from web.backend.ingetrazo_web.app import create_app

    client = TestClient(create_app(tmp_path / "data"))
    state = client.get("/api/v1/library/taxonomy").json()
    by_name = {n["name"]: n for n in state["nodes"]}
    assert state["max_depth"] == 3 and "Furniture" in by_name
    assert state["items"]["component:sofa"] == [by_name["Living room"]["id"]]

    def post(operation, **body):
        return client.post(f"/api/v1/library/taxonomy/{operation}", json=body)

    made = post("create", name="Mine").json()
    mine = next(n for n in made["nodes"] if n["name"] == "Mine")
    assert post("create", name="mine").status_code == 422
    assert post("add", item="component:sofa", node=mine["id"]).json()["items"]["component:sofa"].count(mine["id"]) == 1
    assert post("hide", id=mine["id"], hidden=True).status_code == 200
    assert post("hide", id=mine["id"], hidden="yes").status_code == 422
    assert post("add", item="component:ghost", node=mine["id"]).status_code == 422
    assert post("rename", id=mine["id"], name="Renamed").status_code == 200
    assert post("nonsense").status_code == 404
    after = post("delete", id=mine["id"]).json()
    assert all(n["name"] != "Renamed" for n in after["nodes"])
