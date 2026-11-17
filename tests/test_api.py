import io

from docx import Document

from backend.config import settings

FINANCE = (
    "Quarterly revenue grew 18 percent to 4.2 million rupees. "
    "Operating margin improved because cloud costs fell. " * 6
)
HIRING = "The hiring plan adds five backend engineers and two designers in Pune. " * 6


def ingest(client, name, content):
    response = client.post(
        "/ingest-document", json={"content": content, "document_name": name}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_health_reports_missing_key(client, monkeypatch):
    assert client.get("/health").json()["status"] == "healthy"
    monkeypatch.setattr(settings, "openai_api_key", "sk-your-api-key-here")
    body = client.get("/health").json()
    assert body["status"] == "degraded" and "OPENAI_API_KEY" in body["message"]


def test_llm_call_without_key_is_a_clear_503(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    from backend.services.llm_service import LLMService, llm_service

    monkeypatch.setattr(llm_service, "_chat", LLMService._chat.__get__(llm_service))
    response = client.post(
        "/generate-content", json={"prompt": "hi", "context_retrieval_k": 0}
    )
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_ingest_chunks_lists_and_deletes(client):
    doc = ingest(client, "finance", FINANCE)
    assert doc["chunks"] > 1
    ingest(client, "hiring", HIRING)

    listed = client.get("/documents").json()
    assert {d["document_name"] for d in listed} == {"finance", "hiring"}
    assert client.get("/status").json()["rag_stats"]["document_count"] == 2

    assert client.delete(f"/documents/{doc['document_id']}").status_code == 200
    assert [d["document_name"] for d in client.get("/documents").json()] == ["hiring"]
    assert client.delete("/documents/doc_missing").status_code == 404


def test_generate_uses_the_most_relevant_document(client):
    ingest(client, "finance", FINANCE)
    ingest(client, "hiring", HIRING)
    body = client.post(
        "/generate-content",
        json={"prompt": "How many engineers does the hiring plan add?", "context_retrieval_k": 1},
    ).json()
    assert body["sources"] == ["hiring"]
    assert "From hiring:" in body["content"]  # context reached the LLM prompt


def test_generate_with_empty_knowledge_base(client):
    response = client.post("/generate-content", json={"prompt": "Write a haiku"})
    assert response.status_code == 200
    assert response.json()["sources"] is None


def test_generate_with_placeholders_returns_structured_data(client):
    body = client.post(
        "/generate-content",
        json={"prompt": "Summarise", "template_placeholders": ["SUMMARY", "DATE"]},
    ).json()
    assert body["template_data"] == {
        "SUMMARY": "AI value for SUMMARY",
        "DATE": "AI value for DATE",
    }


def test_fill_placeholders_keeps_known_values(client):
    body = client.post(
        "/fill-placeholders",
        json={
            "prompt": "Q1 report",
            "placeholders": ["TITLE", "SUMMARY"],
            "known_values": {"TITLE": "My fixed title"},
        },
    ).json()
    assert body["values"] == {"TITLE": "My fixed title", "SUMMARY": "AI value for SUMMARY"}


def test_file_ingestion_txt_docx_and_rejects_others(client):
    response = client.post(
        "/ingest-document-file", files={"file": ("notes.txt", FINANCE.encode(), "text/plain")}
    )
    assert response.status_code == 200 and response.json()["document_name"] == "notes"

    doc = Document()
    doc.add_paragraph(HIRING)
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "City", "Pune"
    buffer = io.BytesIO()
    doc.save(buffer)
    response = client.post(
        "/ingest-document-file",
        files={"file": ("plan.docx", buffer.getvalue(), "application/octet-stream")},
        data={"document_name": "Hiring plan"},
    )
    assert response.status_code == 200 and response.json()["document_name"] == "Hiring plan"

    response = client.post(
        "/ingest-document-file", files={"file": ("a.exe", b"MZ", "application/octet-stream")}
    )
    assert response.status_code == 415


def test_pdf_ingestion(client):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    response = client.post(
        "/ingest-document-file", files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")}
    )
    # A page with no text layer is reported, not silently ingested.
    assert response.status_code == 400 and "No text" in response.json()["detail"]


def test_templates_list_upload_and_find(client, template):
    listed = client.get("/templates").json()["templates"]
    assert listed[0]["name"] == "test_template.docx"
    assert "AUTHOR" in listed[0]["placeholders"]

    response = client.post(
        "/templates",
        files={"file": ("copy.docx", template.read_bytes(), "application/octet-stream")},
    )
    assert response.status_code == 200 and response.json()["name"] == "copy.docx"
    bad = client.post("/templates", files={"file": ("bad.docx", b"not a zip", "x/y")})
    assert bad.status_code == 400

    found = client.post("/find-placeholders", params={"template_path": "./templates/copy.docx"})
    assert found.json()["count"] == 6
    missing = client.post("/find-placeholders", params={"template_path": "/etc/passwd"})
    assert missing.status_code == 404


def test_populate_and_download(client, template):
    body = client.post(
        "/populate-template",
        json={
            "template_path": "test_template.docx",
            "placeholders_data": {"TITLE": "Hello", "AUTHOR": "Asha"},
            "output_path": "result.docx",
        },
    ).json()
    assert body["output_path"] == "result.docx"
    assert "NOT_PROVIDED" in body["placeholders_missing"]

    download = client.get(body["download_url"])
    assert download.status_code == 200
    doc = Document(io.BytesIO(download.content))
    assert doc.paragraphs[0].text == "Hello"
    assert client.get("/download/nope.docx").status_code == 404


def test_end_to_end(client, template):
    ingest(client, "finance", FINANCE)
    response = client.post(
        "/end-to-end-generation",
        json={
            "prompt": "Write the quarterly revenue report",
            "template_path": "test_template.docx",
            "known_values": {"DATE": "14 Nov 2026"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sources"] == ["finance"]
    assert body["placeholders_missing"] == []

    doc = Document(io.BytesIO(client.get(body["download_url"]).content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "AI value for SUMMARY" in text and "14 Nov 2026" in text
    assert "{{" not in text


def test_api_key_protection(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    assert client.get("/documents").status_code == 401
    assert client.get("/documents", headers={"X-API-Key": "secret"}).status_code == 200
    assert client.get("/health").status_code == 200  # stays open for probes


def test_addin_is_served(client):
    response = client.get("/addin/taskpane.html")
    assert response.status_code == 200 and "office.js" in response.text


def test_dotenv_wins_over_shell_environment(tmp_path, monkeypatch):
    from backend.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=https://example.test/v1\nOPENAI_MODEL=from-file\n")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("OPENAI_MODEL", "from-shell")
    monkeypatch.setenv("SERVER_PORT", "9999")
    loaded = Settings(_env_file=str(env_file))
    assert loaded.openai_base_url == "https://example.test/v1"
    assert loaded.openai_model == "from-file"
    assert loaded.server_port == 9999  # shell still applies when .env is silent


def test_status_reports_endpoint_and_start_time(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_base_url", "https://example.test/v1")
    body = client.get("/status").json()
    assert body["config"]["api_endpoint"] == "https://example.test/v1"
    assert body["started_at"]
