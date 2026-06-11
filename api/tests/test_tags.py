"""タグ CRUD と所有者分離。"""


async def test_create_and_list_tags(make_user):
    c, _ = await make_user()
    r = await c.post("/api/tags", json={"name": "顧客", "color": "#ff0000"})
    assert r.status_code == 201
    tag = r.json()
    assert tag["name"] == "顧客"
    assert tag["color"] == "#ff0000"

    r = await c.get("/api/tags")
    assert r.status_code == 200
    assert [t["name"] for t in r.json()] == ["顧客"]


async def test_create_tag_requires_auth(client):
    r = await client.post("/api/tags", json={"name": "x"})
    assert r.status_code == 401


async def test_tag_name_validation(make_user):
    c, _ = await make_user()
    r = await c.post("/api/tags", json={"name": ""})
    assert r.status_code == 422
    r = await c.post("/api/tags", json={"name": "x" * 51})
    assert r.status_code == 422


async def test_duplicate_tag_name_rejected(make_user):
    c, _ = await make_user()
    await c.post("/api/tags", json={"name": "dup"})
    r = await c.post("/api/tags", json={"name": "dup"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


async def test_same_tag_name_allowed_for_different_owners(make_user):
    c1, _ = await make_user(email="t1@example.com")
    c2, _ = await make_user(email="t2@example.com")
    r1 = await c1.post("/api/tags", json={"name": "shared-name"})
    r2 = await c2.post("/api/tags", json={"name": "shared-name"})
    assert r1.status_code == 201
    assert r2.status_code == 201


async def test_tags_are_isolated_per_owner(make_user):
    c1, _ = await make_user(email="o1@example.com")
    c2, _ = await make_user(email="o2@example.com")
    await c1.post("/api/tags", json={"name": "only-mine"})
    r = await c2.get("/api/tags")
    assert r.json() == []


async def test_update_tag(make_user):
    c, _ = await make_user()
    tag = (await c.post("/api/tags", json={"name": "old"})).json()
    r = await c.patch(f"/api/tags/{tag['id']}", json={"name": "new", "color": "#0000ff"})
    assert r.status_code == 200
    assert r.json()["name"] == "new"
    assert r.json()["color"] == "#0000ff"


async def test_update_tag_to_existing_name_rejected(make_user):
    c, _ = await make_user()
    await c.post("/api/tags", json={"name": "a"})
    tag_b = (await c.post("/api/tags", json={"name": "b"})).json()
    r = await c.patch(f"/api/tags/{tag_b['id']}", json={"name": "a"})
    assert r.status_code == 400


async def test_update_others_tag_is_404(make_user):
    c1, _ = await make_user(email="u1@example.com")
    c2, _ = await make_user(email="u2@example.com")
    tag = (await c1.post("/api/tags", json={"name": "mine"})).json()
    r = await c2.patch(f"/api/tags/{tag['id']}", json={"name": "hacked"})
    assert r.status_code == 404


async def test_delete_tag(make_user):
    c, _ = await make_user()
    tag = (await c.post("/api/tags", json={"name": "tmp"})).json()
    r = await c.delete(f"/api/tags/{tag['id']}")
    assert r.status_code == 204
    assert (await c.get("/api/tags")).json() == []


async def test_delete_others_tag_is_404(make_user):
    c1, _ = await make_user(email="d1@example.com")
    c2, _ = await make_user(email="d2@example.com")
    tag = (await c1.post("/api/tags", json={"name": "mine"})).json()
    r = await c2.delete(f"/api/tags/{tag['id']}")
    assert r.status_code == 404
