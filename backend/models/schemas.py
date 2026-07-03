from pydantic import BaseModel
from typing import Optional, List


class DocumentRequest(BaseModel):
    """Schema for document ingestion"""
    content: str
    document_name: Optional[str] = "document"
    metadata: Optional[dict] = None


class PromptRequest(BaseModel):
    """Schema for content generation prompt"""
    prompt: str
    context_retrieval_k: Optional[int] = 3
    template_placeholders: Optional[List[str]] = None


class GeneratedContent(BaseModel):
    """Schema for generated content response"""
    content: str
    sources: Optional[List[str]] = None
    template_data: Optional[dict] = None


class TemplatePopulationRequest(BaseModel):
    """Schema for template population request"""
    template_path: str
    placeholders_data: dict
    output_path: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    message: str
