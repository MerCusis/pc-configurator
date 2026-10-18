"""Этап 4: REST API /api/v1 на настоящей тестовой БД."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.importers.docyx import SOURCE
from app.models.catalog import Category, Part
from app.scripts.seed import seed

API = "/api/v1"
BASE = ["amd-ryzen5-7600", "msi-b650-gaming-plus-wifi", "kingston-fury-ddr5-32-6000", "palit-rtx4060-dual",
        "samsung-990pro-1tb", "deepcool-pk650d", "bequiet-pure-base-500", "deepcool-ak400"]
NBSP = "\u00a0"


@pytest.fixture
def api(db):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.api.sessions import session_rate_limit
    from app.database import get_db
    from app.main import app

    db.run(seed)
    engine = create_async_engine(db.url, poolclass=NullPool)

    async def _get_db():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def _no_limit():
        return None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[session_rate_limit] = _no_limit
    client = TestClient(app)
    client.ids = db.run(_seed_ids)
    client.db = db
    yield client
    app.dependency_overrides.clear()


async def _seed_ids(session):
    rows = (await session.execute(select(Part.external_id, Part.id).where(Part.source == "seed"))).all()
    return dict(rows)


def token(client) -> dict[str, str]:
    r = client.post(f"{API}/session")
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["anon_token"]) >= 40 and body["builds_limit"] == 15
    return {"Authorization": f"Bearer {body['anon_token']}"}


def items(client, keys):
    return [{"part_id": client.ids[k], "quantity": 1} for k in keys]


def build_body(client, keys=BASE, name="Игровой ПК"):
    return {"name": name, "description": "тест", "items": items(client, keys)}


@pytest.mark.db
def test_session_required_and_invalid_token(api):
    assert api.get(f"{API}/builds").status_code == 401
    r = api.get(f"{API}/builds", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_token"
    h = token(api)
    assert api.get(f"{API}/session", headers=h).json()["builds_count"] == 0


@pytest.mark.db
def test_catalog_categories_filters_search(api):
    cats = api.get(f"{API}/categories").json()
    assert {c["slug"] for c in cats} >= {"cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler"}
    assert all(c["part_count"] >= 1 for c in cats)

    r = api.get(f"{API}/parts", params={"category": "cpu", "socket": "AM5"}).json()
    assert r["total"] >= 1 and all(p["specs"]["socket"] == "AM5" for p in r["items"])
    assert api.ids["amd-ryzen5-7600"] in {p["id"] for p in r["items"]}

    coolers = api.get(f"{API}/parts", params={"category": "cooler", "socket": "AM5"}).json()
    assert coolers["total"] >= 1 and all("AM5" in p["specs"]["sockets"] for p in coolers["items"])

    part = api.get(f"{API}/parts/{api.ids['amd-ryzen5-7600']}").json()
    assert part["price_display"].endswith(f"{NBSP}₽") and part["price_is_estimate"] is False
    found = api.get(f"{API}/parts", params={"q": part["name"][:8].lower()}).json()
    assert part["id"] in {p["id"] for p in found["items"]}
    assert api.get(f"{API}/parts", params={"q": "%_"}).json()["total"] == 0

    prices = [Decimal(p["price"]) for p in api.get(f"{API}/parts", params={"sort": "price", "limit": 100}).json()["items"]
              if p["price"]]
    assert prices == sorted(prices)
    assert api.get(f"{API}/parts/999999").status_code == 404
    assert api.get(f"{API}/manufacturers", params={"category": "cpu"}).json()


@pytest.mark.db
def test_no_data_labels_and_estimated_price(api):
    async def add(session):
        cat = await session.scalar(select(Category.id).where(Category.slug == "cpu"))
        bare = Part(category_id=cat, name="Test CPU без данных", source=SOURCE, external_id="t-1",
                    specs={"socket": "AM5"}, currency="RUB")
        full = Part(category_id=cat, name="Test CPU с ценой", source=SOURCE, external_id="t-2",
                    specs={"socket": "AM5", "memory_types": ["DDR5"], "tdp_w": 65, "integrated_graphics": True},
                    power_w=88, price=Decimal("19990"), currency="RUB")
        session.add_all([bare, full])
        await session.commit()
        return bare.id, full.id

    bare_id, full_id = api.db.run(add)
    bare = api.get(f"{API}/parts/{bare_id}").json()
    assert bare["price"] is None and bare["price_display"] == "нет данных" and bare["has_price"] is False
    assert bare["power_display"] == "нет данных" and bare["manufacturer_display"] == "нет данных"
    assert {"tdp_w", "memory_types", "integrated_graphics", "power_w"} <= set(bare["missing_specs"])
    tdp = next(s for s in bare["specs_display"] if s["key"] == "tdp_w")
    assert tdp == {"key": "tdp_w", "label": "TDP", "value": "нет данных", "missing": True}
    assert bare["is_data_complete"] is False

    full = api.get(f"{API}/parts/{full_id}").json()
    assert full["price_display"] == f"19{NBSP}990{NBSP}₽"
    assert full["price_is_estimate"] is True and full["price_note"] == "ориентировочная цена"
    assert next(s for s in full["specs_display"] if s["key"] == "tdp_w")["value"] == f"65{NBSP}Вт"

    unpriced = api.get(f"{API}/parts", params={"category": "cpu", "has_price": "false"}).json()
    assert [p["id"] for p in unpriced["items"]] == [bare_id]

    only_bare = api.post(f"{API}/compatibility/check", json={"items": [{"part_id": bare_id}]}).json()
    assert only_bare["total_price_display"] == "нет данных" and only_bare["unpriced_count"] == 1
    mixed = api.post(f"{API}/compatibility/check", json={"items": [
        {"part_id": bare_id}, {"part_id": api.ids["msi-b650-gaming-plus-wifi"]},
        # память нужна, чтобы правило ram_type_cpu обратилось к пустому memory_types процессора
        {"part_id": api.ids["kingston-fury-ddr5-32-6000"]}]}).json()
    assert "без учёта позиций без цены: 1" in mixed["total_price_note"]
    missing = [i for i in mixed["issues"] if i["code"] == "missing_specs"]
    assert any(i["details"].get("key") == "memory_types" for i in missing), mixed["issues"]
    assert all(i["severity"] == "warning" for i in missing)


@pytest.mark.db
def test_compatibility_endpoint(api):
    ok = api.post(f"{API}/compatibility/check", json={"items": items(api, BASE)}).json()
    assert ok["is_complete"] and ok["error_count"] == 0 and ok["total_price_note"] is None
    bad_keys = ["gigabyte-b550m-ds3h" if k == "msi-b650-gaming-plus-wifi" else k for k in BASE]
    bad = api.post(f"{API}/compatibility/check", json={"items": items(api, bad_keys)}).json()
    assert {"socket_mismatch", "ram_type_motherboard"} <= {i["code"] for i in bad["issues"]}
    r = api.post(f"{API}/compatibility/check", json={"items": [{"part_id": 999999}]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_parts"
    assert api.post(f"{API}/compatibility/check", json={"items": [{"part_id": 1, "quantity": 0}]}).status_code == 422


@pytest.mark.db
def test_build_crud_and_share(api):
    h = token(api)
    r = api.post(f"{API}/builds", json=build_body(api), headers=h)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["check"]["is_complete"] and len(b["items"]) == 8 and b["is_public"] is False
    assert b["total_price_display"].endswith("₽") and all(i["price_snapshot"] for i in b["items"])

    listed = api.get(f"{API}/builds", headers=h).json()
    assert listed["count"] == 1 and listed["items"][0]["item_count"] == 8

    upd = api.put(f"{API}/builds/{b['id']}", headers=h,
                  json=build_body(api, [k for k in BASE if k != "palit-rtx4060-dual"], name="  Без видеокарты "))
    assert upd.status_code == 200 and upd.json()["name"] == "Без видеокарты" and len(upd.json()["items"]) == 7

    other = token(api)
    assert api.get(f"{API}/builds/{b['id']}", headers=other).status_code == 404
    assert api.delete(f"{API}/builds/{b['id']}", headers=other).status_code == 404

    share = api.post(f"{API}/builds/{b['id']}/share", headers=h).json()
    pub = api.get(f"{API}/shared/{share['share_slug']}")
    assert pub.status_code == 200 and pub.json()["is_owner"] is False and "session_id" not in pub.json()
    assert api.delete(f"{API}/builds/{b['id']}/share", headers=h).status_code == 204
    assert api.get(f"{API}/shared/{share['share_slug']}").status_code == 404

    assert api.delete(f"{API}/builds/{b['id']}", headers=h).status_code == 204
    assert api.get(f"{API}/builds/{b['id']}", headers=h).status_code == 404


@pytest.mark.db
def test_incompatible_and_invalid_builds_rejected(api):
    h = token(api)
    bad_keys = ["gigabyte-b550m-ds3h" if k == "msi-b650-gaming-plus-wifi" else k for k in BASE]
    r = api.post(f"{API}/builds", json=build_body(api, bad_keys), headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "incompatible_build"
    assert api.post(f"{API}/builds", json={"name": "   ", "items": []}, headers=h).status_code == 422
    draft = api.post(f"{API}/builds", json=build_body(api, ["amd-ryzen5-7600"], name="Черновик"), headers=h)
    assert draft.status_code == 201 and draft.json()["check"]["missing_categories"]


@pytest.mark.db
def test_build_limit_15(api):
    h = token(api)
    for n in range(15):
        assert api.post(f"{API}/builds", json={"name": f"#{n}", "items": []}, headers=h).status_code == 201
    r = api.post(f"{API}/builds", json={"name": "лишняя", "items": []}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "build_limit"
    assert api.post(f"{API}/builds", json={"name": "чужая", "items": []}, headers=token(api)).status_code == 201


@pytest.mark.db
def test_retired_part_marked_unavailable(api):
    h = token(api)
    b = api.post(f"{API}/builds", json=build_body(api), headers=h).json()

    async def retire(session):
        part = await session.get(Part, api.ids["palit-rtx4060-dual"])
        part.is_active = False
        await session.commit()

    api.db.run(retire)
    got = api.get(f"{API}/builds/{b['id']}", headers=h).json()
    assert got["unavailable_part_ids"] == [api.ids["palit-rtx4060-dual"]]
    assert sum(not i["is_available"] for i in got["items"]) == 1


def test_import_cli_defaults(monkeypatch):
    from app.scripts.import_docyx import FILES, _retire_seed, parse_args

    monkeypatch.delenv("DOCYX_USD_RUB_RATE", raising=False)
    with pytest.raises(SystemExit):
        parse_args([])
    assert parse_args(["--keep-usd"]).usd_rub_rate is None
    monkeypatch.setenv("DOCYX_USD_RUB_RATE", "95,5")
    a = parse_args([])
    assert a.usd_rub_rate == Decimal("95.5") and not a.skip_unpriced and not a.keep_seed
    assert _retire_seed(a, list(FILES)) and not _retire_seed(a, ["cpu"])
    assert not _retire_seed(parse_args(["--keep-seed"]), list(FILES))
