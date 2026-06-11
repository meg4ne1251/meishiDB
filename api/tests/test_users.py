"""共有先候補を探す /users/search。"""


async def test_search_finds_other_users_by_name(make_user):
    await make_user(email="alice@example.com", display_name="Alice Anderson")
    bob_c, _ = await make_user(email="bob@example.com", display_name="Bob")
    r = await bob_c.get("/api/users/search", params={"q": "Alice"})
    assert r.status_code == 200
    results = r.json()
    assert any(u["email"] == "alice@example.com" for u in results)


async def test_search_matches_email(make_user):
    await make_user(email="charlie@example.com", display_name="Charlie")
    me_c, _ = await make_user(email="me@example.com", display_name="Me")
    r = await me_c.get("/api/users/search", params={"q": "charlie@"})
    assert [u["email"] for u in r.json()] == ["charlie@example.com"]


async def test_search_excludes_self(make_user):
    me_c, _ = await make_user(email="onlyme@example.com", display_name="OnlyMe")
    r = await me_c.get("/api/users/search", params={"q": "OnlyMe"})
    assert r.json() == []


async def test_search_requires_query(make_user):
    c, _ = await make_user()
    r = await c.get("/api/users/search", params={"q": ""})
    assert r.status_code == 422


async def test_search_requires_auth(client):
    r = await client.get("/api/users/search", params={"q": "x"})
    assert r.status_code == 401


async def test_search_limit(make_user):
    # 12 人作って、共通語で引っかけても 10 件まで
    searcher_c, _ = await make_user(email="searcher@example.com", display_name="Searcher")
    for i in range(12):
        await make_user(email=f"common{i}@example.com", display_name=f"Common Person {i}")
    r = await searcher_c.get("/api/users/search", params={"q": "Common"})
    assert len(r.json()) == 10
