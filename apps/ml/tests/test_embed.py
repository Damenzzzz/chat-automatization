import math

from fastapi.testclient import TestClient


def test_health_shows_loaded_models(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["embedder"] == {
        "backend": "fake",
        "model": "fake-embedder",
        "loaded": True,
        "dim": 1024,
    }


def test_embed_contract(client: TestClient) -> None:
    response = client.post("/embed", json={"texts": ["Букет пионов", "Розы"], "kind": "document"})
    assert response.status_code == 200
    body = response.json()
    assert body["dim"] == 1024
    assert len(body["embeddings"]) == 2
    for vec in body["embeddings"]:
        assert len(vec) == 1024
        assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-6)


def test_query_and_document_kinds_differ(client: TestClient) -> None:
    text = {"texts": ["пионы на сегодня"]}
    query = client.post("/embed", json={**text, "kind": "query"}).json()["embeddings"][0]
    doc = client.post("/embed", json={**text, "kind": "document"}).json()["embeddings"][0]
    assert query != doc
    again = client.post("/embed", json={**text, "kind": "query"}).json()["embeddings"][0]
    assert again == query


def test_embed_limits(client: TestClient) -> None:
    assert client.post("/embed", json={"texts": []}).status_code == 422
    assert client.post("/embed", json={"texts": ["x"] * 9}).status_code == 413
    assert client.post("/embed", json={"texts": ["x" * 9000]}).status_code == 413
    assert client.post("/embed", json={"texts": ["x"], "kind": "other"}).status_code == 422
