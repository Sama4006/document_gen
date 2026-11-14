"""Test fixtures: the OpenAI API is replaced with deterministic fakes."""

import hashlib
import json
import math
import re
import uuid

import chromadb
import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.services.llm_service import llm_service
from backend.services.rag_service import rag_service


def fake_embed(texts):
    """Bag-of-words hashing embedding: similar words give similar vectors."""
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        vectors.append([v / norm for v in vector])
    return vectors


def fake_chat(system, user, json_mode=False):
    if json_mode:
        names = json.loads(user.rsplit("Placeholders to fill (JSON keys):\n", 1)[1])
        return json.dumps({name: f"AI value for {name}" for name in names})
    return "GENERATED: " + user[:200]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "templates_dir", str(tmp_path / "templates"))
    monkeypatch.setattr(settings, "output_dir", str(tmp_path / "output"))
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "api_key", None)
    monkeypatch.setattr(settings, "chunk_size", 200)
    monkeypatch.setattr(settings, "chunk_overlap", 40)

    monkeypatch.setattr(rag_service, "_client", chromadb.EphemeralClient())
    monkeypatch.setattr(rag_service, "_collection", None)
    monkeypatch.setattr(rag_service, "_collection_name", f"test_{uuid.uuid4().hex}")
    monkeypatch.setattr(rag_service, "_embed", fake_embed)
    monkeypatch.setattr(llm_service, "_chat", fake_chat)

    (tmp_path / "templates").mkdir()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def template(tmp_path, client):
    """A template whose tokens are split across runs, in a table and a header."""
    doc = Document()
    doc.add_heading("{{TITLE}}", 0)

    split = doc.add_paragraph()
    split.add_run("Prepared by ").bold = True
    for piece in ("{", "{AUT", "HOR}", "}"):  # Word often splits tokens like this
        split.add_run(piece).italic = True
    split.add_run(" on {{ DATE }}.")

    doc.add_paragraph("{{SUMMARY}}")
    doc.add_paragraph("Untouched: {{NOT_PROVIDED}}")

    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Status"
    table.rows[0].cells[1].text = "{{STATUS}}"

    doc.sections[0].header.paragraphs[0].text = "Confidential - {{TITLE}}"

    path = tmp_path / "templates" / "test_template.docx"
    doc.save(str(path))
    return path
