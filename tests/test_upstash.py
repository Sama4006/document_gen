"""Run the knowledge-base API against a fake Upstash Vector REST server."""

import base64
import io
import json
import math

import httpx
import pytest
from docx import Document

from backend.config import settings
from backend.services.rag_service import UpstashStore, fit_dimensions, rag_service

DIMENSION = 32


class FakeUpstash:
    def __init__(self):
        self.vectors = {}  # id -> (vector, metadata)
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        path = request.url.path.strip("/")
        body = json.loads(request.content) if request.content else None
        self.calls.append(path)
        if path == "info":
            return self._ok({"vectorCount": len(self.vectors), "dimension": DIMENSION})
        if path == "upsert":
            for record in body:
                if len(record["vector"]) != DIMENSION:
                    return httpx.Response(422, json={"error": "Invalid vector dimension"})
                self.vectors[record["id"]] = (record["vector"], record["metadata"])
            return self._ok("Success")
        if path == "query":
            def score(item):
                return sum(a * b for a, b in zip(body["vector"], item[1][0]))
            ranked = sorted(self.vectors.items(), key=score, reverse=True)[: body["topK"]]
            return self._ok([{"id": i, "score": 0.9, "metadata": v[1]} for i, v in ranked])
        if path == "range":
            ids = sorted(self.vectors)
            start = int(body["cursor"])
            page = ids[start : start + 2]  # small pages to exercise the cursor loop
            next_cursor = str(start + 2) if start + 2 < len(ids) else ""
            return self._ok({
                "nextCursor": next_cursor,
                "vectors": [{"id": i, "metadata": self.vectors[i][1]} for i in page],
            })
        if path == "delete":
            deleted = sum(1 for i in body["ids"] if self.vectors.pop(i, None))
            return self._ok({"deleted": deleted})
        return httpx.Response(404, json={"error": f"unknown path {path}"})

    @staticmethod
    def _ok(result):
        return httpx.Response(200, json={"result": result})


@pytest.fixture
def upstash(client, monkeypatch):
    fake = FakeUpstash()
    store = UpstashStore(
        "https://fake-upstash.test", "test-token",
        http_client=httpx.Client(transport=httpx.MockTransport(fake)),
    )
    monkeypatch.setattr(rag_service, "_upstash", store)
    return fake


def test_fit_dimensions_truncates_and_normalises():
    (vector,) = fit_dimensions([[3.0, 4.0, 12.0]], 2)
    assert vector == pytest.approx([0.6, 0.8])
    assert math.isclose(sum(v * v for v in vector), 1.0)
    with pytest.raises(ValueError, match="expects 4"):
        fit_dimensions([[1.0, 2.0]], 4)


def test_knowledge_base_round_trip_on_upstash(client, upstash):
    finance = "Quarterly revenue grew 18 percent. Operating margin improved. " * 8
    hiring = "The hiring plan adds five backend engineers in Pune. " * 8

    first = client.post("/ingest-document", json={"content": finance, "document_name": "finance"})
    assert first.status_code == 200, first.text
    client.post("/ingest-document", json={"content": hiring, "document_name": "hiring"})
    assert first.json()["chunks"] > 1
    assert all(len(v[0]) == DIMENSION for v in upstash.vectors.values())  # fitted to the index

    listed = client.get("/documents").json()
    assert {d["document_name"] for d in listed} == {"finance", "hiring"}  # paged through range

    body = client.post(
        "/generate-content",
        json={"prompt": "How many engineers does the hiring plan add?", "context_retrieval_k": 1},
    ).json()
    assert body["sources"] == ["hiring"]
    assert "From hiring:" in body["content"]  # text came back from metadata

    status = client.get("/status").json()
    assert status["config"]["vector_store"] == "upstash"
    assert status["rag_stats"]["document_count"] == 2

    assert client.delete(f"/documents/{first.json()['document_id']}").status_code == 200
    assert [d["document_name"] for d in client.get("/documents").json()] == ["hiring"]
    assert client.delete("/documents/doc_missing").status_code == 404


def test_upstash_errors_are_reported(client, monkeypatch):
    store = UpstashStore(
        "https://fake-upstash.test", "wrong",
        http_client=httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(401, json={"error": "Unauthorized: invalid token"}))),
    )
    monkeypatch.setattr(rag_service, "_upstash", store)
    response = client.post("/ingest-document", json={"content": "hello there"})
    assert response.status_code == 500
    assert "Upstash Vector error (401): Unauthorized" in response.json()["detail"]


def test_generated_document_is_returned_inline(client, template):
    body = client.post(
        "/populate-template",
        json={"template_path": "test_template.docx", "placeholders_data": {"TITLE": "Inline"}},
    ).json()
    doc = Document(io.BytesIO(base64.b64decode(body["document_base64"])))
    assert doc.paragraphs[0].text == "Inline"


def test_manifest_points_at_the_serving_host(client):
    response = client.get(
        "/addin/manifest.xml",
        headers={"host": "docgen.vercel.app", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 200
    assert "https://docgen.vercel.app/addin/taskpane.html" in response.text
    assert "localhost:8000" not in response.text


def test_serverless_paths_use_tmp(monkeypatch, tmp_path):
    from backend.config import Settings

    monkeypatch.setenv("VERCEL", "1")
    loaded = Settings(_env_file=None)
    assert str(loaded.output_path) == "/tmp/output"
    assert str(loaded.template_upload_path) == "/tmp/templates"
    assert loaded.templates_path.name == "templates"  # bundled ones still found


def test_uploaded_templates_live_beside_bundled_ones(client, template, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "template_upload_dir", str(tmp_path / "uploads"))
    response = client.post(
        "/templates",
        files={"file": ("mine.docx", template.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200
    assert (tmp_path / "uploads" / "mine.docx").is_file()
    names = [t["name"] for t in client.get("/templates").json()["templates"]]
    assert names == ["mine.docx", "test_template.docx"]
    found = client.post("/find-placeholders", params={"template_path": "mine.docx"})
    assert found.status_code == 200
