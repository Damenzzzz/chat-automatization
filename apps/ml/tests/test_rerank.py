from fastapi.testclient import TestClient


def test_rerank_contract(client: TestClient) -> None:
    docs = ["Тормозные колодки", "Розовые пионы букет", "пионы"]
    response = client.post("/rerank", json={"query": "розовые пионы", "documents": docs})

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "fake-reranker"
    assert len(body["scores"]) == 3
    assert body["scores"][1] > body["scores"][2] > body["scores"][0]


def test_rerank_limits(client: TestClient) -> None:
    assert client.post("/rerank", json={"query": "", "documents": ["x"]}).status_code == 422
    assert client.post("/rerank", json={"query": "x", "documents": []}).status_code == 422
    too_many = {"query": "x", "documents": ["d"] * 101}
    assert client.post("/rerank", json=too_many).status_code == 413
