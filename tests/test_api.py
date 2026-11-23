async def _post(client, path, sku="A-100", qty=10, wh="WH-1"):
    return await client.post(
        path, json={"sku": sku, "qty": qty, "warehouse": wh}
    )


async def test_receipt_issue_and_stock(client):
    r = await _post(client, "/receipts", qty=50)
    assert r.status == 201
    r = await _post(client, "/issues", qty=20)
    assert r.status == 201

    r = await client.get("/stock", params={"warehouse": "WH-1"})
    assert r.status == 200
    assert (await r.json())["items"] == [{"sku": "A-100", "qty": 30}]

    r = await client.get(
        "/stock", params={"warehouse": "WH-1", "sku": "A-100"}
    )
    assert (await r.json())["items"] == [{"sku": "A-100", "qty": 30}]


async def test_issue_more_than_available_is_rejected(client):
    await _post(client, "/receipts", qty=5)
    r = await _post(client, "/issues", qty=6)
    assert r.status == 409
    assert (await r.json())["details"] == {"available": 5, "requested": 6}


async def test_validation(client):
    assert (await _post(client, "/receipts", qty=0)).status == 422
    assert (await _post(client, "/receipts", qty=-3)).status == 422
    assert (await client.post("/receipts", json={"sku": "X"})).status == 422
    assert (await client.post("/receipts", data="not json")).status == 400
    assert (await client.get("/stock")).status == 400


async def test_summary(client):
    await _post(client, "/receipts", sku="A", qty=100, wh="WH-1")
    await _post(client, "/receipts", sku="B", qty=40, wh="WH-1")
    await _post(client, "/receipts", sku="A", qty=60, wh="WH-2")
    await _post(client, "/receipts", sku="C", qty=5, wh="WH-2")
    await _post(client, "/issues", sku="B", qty=40, wh="WH-1")

    r = await client.get("/stock/summary", params={"top_n": 2})
    data = await r.json()
    assert data["warehouses"] == [
        {"warehouse": "WH-1", "total_qty": 100, "sku_count": 1},
        {"warehouse": "WH-2", "total_qty": 65, "sku_count": 2},
    ]
    assert data["top_skus"] == [
        {"sku": "A", "total_qty": 160},
        {"sku": "C", "total_qty": 5},
    ]

    r = await client.get("/stock/summary")  # top_n по умолчанию = 5
    assert len((await r.json())["top_skus"]) == 2
    assert (
        await client.get("/stock/summary", params={"top_n": "x"})
    ).status == 400
