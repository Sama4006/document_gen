"""FastAPI backend for AI-powered Word document generation.

Endpoints are plain `def` functions on purpose: the OpenAI, ChromaDB and
python-docx calls are blocking, so FastAPI runs them in its thread pool
instead of stalling the event loop.
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.config import PROJECT_ROOT, settings
from backend.models.schemas import (
    DocumentInfo,
    DocumentRequest,
    EndToEndRequest,
    FillPlaceholdersRequest,
    FillPlaceholdersResponse,
    GeneratedContent,
    HealthResponse,
    IngestResponse,
    PromptRequest,
    TemplatePopulationRequest,
)
from backend.services import document_loader
from backend.services.llm_service import LLMNotConfigured, llm_service
from backend.services.rag_service import rag_service
from backend.services.template_engine import template_engine

logger = logging.getLogger("docgen")

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ADDIN_DIR = PROJECT_ROOT / "frontend" / "word-plugin"


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Optional shared-secret auth, enabled by setting API_KEY in .env."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


app = FastAPI(
    title="Word Template + LLM + RAG API",
    description="Backend API for AI-powered Word document generation",
    version="2.0.0",
)

_origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Browsers reject credentials combined with a wildcard origin.
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

protected = [Depends(require_api_key)]


# ==================== Error handling ====================

@app.exception_handler(LLMNotConfigured)
def _llm_not_configured(_, exc: LLMNotConfigured):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(FileNotFoundError)
def _not_found(_, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(document_loader.UnsupportedFileType)
def _unsupported(_, exc: document_loader.UnsupportedFileType):
    return JSONResponse(status_code=415, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def _bad_request(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
def _unexpected(_, exc: Exception):
    try:
        from openai import APIStatusError, OpenAIError
    except ImportError:  # pragma: no cover
        APIStatusError = OpenAIError = ()
    if isinstance(exc, APIStatusError):
        # e.g. bad key, unknown model, rate limit: pass the reason through.
        message = getattr(exc, "message", str(exc))
        return JSONResponse(status_code=502, content={"detail": f"OpenAI error: {message}"})
    if isinstance(exc, OpenAIError):
        return JSONResponse(status_code=502, content={"detail": f"OpenAI error: {exc}"})
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": str(exc) or type(exc).__name__})


# ==================== Health & status ====================

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/addin/taskpane.html" if ADDIN_DIR.is_dir() else "/docs")


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Cheap liveness check. Does not spend OpenAI credits."""
    try:
        rag_service.get_collection_stats()
    except Exception as exc:
        return HealthResponse(status="unhealthy", message=f"Vector store error: {exc}")
    if not llm_service.configured:
        return HealthResponse(
            status="degraded",
            message="Server is running, but OPENAI_API_KEY is not set in .env",
        )
    return HealthResponse(status="healthy", message="All services operational")


@app.get("/status", dependencies=protected)
def get_status(check_llm: bool = False):
    """System statistics. `check_llm=true` also makes a live OpenAI call."""
    status = {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "rag_stats": rag_service.get_collection_stats(),
        "templates": len(template_engine.list_templates()),
        "config": {
            "model": settings.openai_model,
            "embedding_model": settings.openai_embedding_model,
            "collection": settings.collection_name,
            "llm_configured": llm_service.configured,
        },
    }
    if check_llm:
        try:
            llm_service.get_embedding("ping")
            status["llm_check"] = "ok"
        except Exception as exc:
            status["llm_check"] = f"failed: {exc}"
    return status


# ==================== Knowledge base ====================

def _new_document_id() -> str:
    return f"doc_{uuid.uuid4().hex[:12]}"


@app.post("/ingest-document", response_model=IngestResponse, dependencies=protected)
def ingest_document(request: DocumentRequest):
    """Add raw text to the knowledge base (chunked and embedded)."""
    if not request.content.strip():
        raise ValueError("Document content is empty.")
    result = rag_service.ingest_document(
        document_id=_new_document_id(),
        content=request.content,
        document_name=request.document_name,
        metadata=request.metadata,
    )
    return IngestResponse(**result)


@app.post("/ingest-document-file", response_model=IngestResponse, dependencies=protected)
def ingest_document_file(
    file: UploadFile = File(...),
    document_name: Optional[str] = Form(default=None),
):
    """Add a .txt, .md, .docx or .pdf file to the knowledge base."""
    data = _read_upload(file)
    text = document_loader.extract_text(file.filename or "", data)
    if not text.strip():
        raise ValueError(
            "No text could be extracted from this file "
            "(scanned PDFs need OCR before upload)."
        )
    result = rag_service.ingest_document(
        document_id=_new_document_id(),
        content=text,
        document_name=document_name or Path(file.filename or "document").stem,
        metadata={"source": "file_upload", "filename": file.filename or ""},
    )
    return IngestResponse(**result, message="Document file ingested successfully")


@app.get("/documents", response_model=List[DocumentInfo], dependencies=protected)
def list_documents():
    return rag_service.list_documents()


@app.delete("/documents/{document_id}", dependencies=protected)
def delete_document(document_id: str):
    removed = rag_service.delete_document(document_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "success", "document_id": document_id, "chunks_removed": removed}


def _read_upload(file: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"File is larger than {settings.max_upload_mb} MB"
        )
    if not data:
        raise ValueError("Uploaded file is empty.")
    return data


# ==================== Content generation ====================

def _retrieve(query: str, k: int):
    documents, metadatas = rag_service.retrieve_context(query=query, k=k)
    context = rag_service.format_context(documents, metadatas)
    return context or None, rag_service.source_names(metadatas)


@app.post("/generate-content", response_model=GeneratedContent, dependencies=protected)
def generate_content(request: PromptRequest):
    """Generate free-form content with RAG context.

    If `template_placeholders` is given, the response also contains
    `template_data` with one generated value per placeholder.
    """
    context, sources = _retrieve(request.prompt, request.context_retrieval_k)
    content = llm_service.generate_content(prompt=request.prompt, context=context)

    template_data = None
    if request.template_placeholders:
        template_data = llm_service.generate_placeholder_values(
            prompt=f"{request.prompt}\n\nDraft content to draw from:\n{content}",
            placeholders=request.template_placeholders,
            context=context,
        )
    return GeneratedContent(
        content=content, sources=sources or None, template_data=template_data
    )


@app.post(
    "/fill-placeholders", response_model=FillPlaceholdersResponse, dependencies=protected
)
def fill_placeholders(request: FillPlaceholdersRequest):
    """Generate a value for each placeholder name (used by the Word add-in)."""
    context, sources = _retrieve(request.prompt, request.context_retrieval_k)
    values = llm_service.generate_placeholder_values(
        prompt=request.prompt,
        placeholders=request.placeholders,
        context=context,
        known_values=request.known_values,
    )
    return FillPlaceholdersResponse(values=values, sources=sources)


# ==================== Templates ====================

@app.get("/templates", dependencies=protected)
def list_templates():
    """Templates available on the server, with their placeholders."""
    return {"templates": template_engine.list_templates()}


@app.post("/templates", dependencies=protected)
def upload_template(file: UploadFile = File(...)):
    """Upload a .docx template to the templates directory."""
    if not (file.filename or "").lower().endswith(".docx"):
        raise document_loader.UnsupportedFileType("Templates must be .docx files.")
    path = template_engine.save_template(file.filename, _read_upload(file))
    return {
        "status": "success",
        "name": path.name,
        "placeholders": template_engine.find_placeholders(path),
    }


@app.post("/find-placeholders", dependencies=protected)
def find_placeholders(template_path: str):
    """List the `{{PLACEHOLDER}}` names in a server-side template."""
    path = template_engine.resolve_template(template_path)
    placeholders = template_engine.find_placeholders(path)
    return {
        "template_path": path.name,
        "placeholders_found": placeholders,
        "count": len(placeholders),
    }


def _populate(template_name: str, data: dict, output_name: Optional[str]) -> dict:
    template = template_engine.resolve_template(template_name)
    output, report = template_engine.populate_template(template, data, output_name)
    return {
        "status": "success",
        "output_path": output.name,
        "download_url": f"/download/{output.name}",
        "placeholders_filled": report["filled"],
        "placeholders_missing": report["missing"],
        "message": "Template populated successfully",
    }


@app.post("/populate-template", dependencies=protected)
def populate_template(request: TemplatePopulationRequest):
    """Fill a server-side template with the given values."""
    return _populate(request.template_path, request.placeholders_data, request.output_path)


@app.get("/download/{filename}", dependencies=protected)
def download(filename: str):
    """Download a generated document."""
    path = template_engine.resolve_output(filename)
    return FileResponse(path, media_type=DOCX_MIME, filename=path.name)


# ==================== Workflow ====================

@app.post("/end-to-end-generation", dependencies=protected)
def end_to_end_generation(request: EndToEndRequest):
    """Prompt in, finished document out.

    1. Read the template's placeholders
    2. Retrieve context from the knowledge base
    3. Ask the LLM for a value per placeholder
    4. Fill the template and save it
    """
    template = template_engine.resolve_template(request.template_path)
    placeholders = template_engine.find_placeholders(template)
    if not placeholders:
        raise ValueError(f"No {{{{PLACEHOLDER}}}} tokens found in {template.name}.")

    context, sources = _retrieve(request.prompt, request.context_retrieval_k)
    values = llm_service.generate_placeholder_values(
        prompt=request.prompt,
        placeholders=placeholders,
        context=context,
        known_values=request.known_values,
    )
    result = _populate(template.name, values, request.output_path)
    result.update(
        {
            "generated_values": values,
            "sources": sources,
            "populated_document": result["output_path"],
        }
    )
    return result


# ==================== Word add-in (static files) ====================

if ADDIN_DIR.is_dir():
    app.mount("/addin", StaticFiles(directory=str(ADDIN_DIR), html=True), name="addin")
