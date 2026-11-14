"""Request and response models."""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentRequest(BaseModel):
    content: str = Field(..., min_length=1)
    document_name: str = "document"
    metadata: Optional[dict] = None


class IngestResponse(BaseModel):
    status: str = "success"
    document_id: str
    document_name: str
    chunks: int
    characters: int
    message: str = "Document ingested successfully"


class DocumentInfo(BaseModel):
    document_id: str
    document_name: str
    chunks: int


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    context_retrieval_k: int = Field(3, ge=0, le=20)
    template_placeholders: Optional[List[str]] = None


class GeneratedContent(BaseModel):
    content: str
    sources: Optional[List[str]] = None
    template_data: Optional[Dict[str, str]] = None


class FillPlaceholdersRequest(BaseModel):
    """Ask the LLM for one value per placeholder."""

    prompt: str = Field(..., min_length=1)
    placeholders: List[str] = Field(..., min_length=1)
    context_retrieval_k: int = Field(3, ge=0, le=20)
    # Values the user already knows; the LLM only fills the rest.
    known_values: Optional[Dict[str, str]] = None


class FillPlaceholdersResponse(BaseModel):
    values: Dict[str, str]
    sources: List[str] = []


class TemplatePopulationRequest(BaseModel):
    # Name of a template in the templates directory, e.g. "report_template.docx".
    template_path: str
    placeholders_data: Dict[str, str]
    # Optional output file name (stored in the output directory).
    output_path: Optional[str] = None


class EndToEndRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    template_path: str
    output_path: Optional[str] = None
    context_retrieval_k: int = Field(3, ge=0, le=20)
    known_values: Optional[Dict[str, str]] = None


class HealthResponse(BaseModel):
    status: str
    message: str
