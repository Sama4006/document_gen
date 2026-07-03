"""FastAPI Backend - Main application entry point"""

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from backend.config import settings
from backend.models.schemas import (
    DocumentRequest, PromptRequest, GeneratedContent,
    TemplatePopulationRequest, HealthResponse
)
from backend.services.llm_service import llm_service
from backend.services.rag_service import rag_service
from backend.services.template_engine import template_engine
import uuid
from datetime import datetime
import os


# Initialize FastAPI app
app = FastAPI(
    title="Word Template + LLM + RAG API",
    description="Backend API for AI-powered Word document generation",
    version="1.0.0"
)

# Add CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Health & Status ====================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test LLM connection
        llm_service.client.models.list()
        # Test RAG connection
        stats = rag_service.get_collection_stats()
        
        return HealthResponse(
            status="healthy",
            message="All services operational"
        )
    except Exception as e:
        return HealthResponse(
            status="unhealthy",
            message=str(e)
        )


@app.get("/status")
async def get_status():
    """Get system status and statistics"""
    try:
        rag_stats = rag_service.get_collection_stats()
        return {
            "status": "running",
            "timestamp": datetime.now().isoformat(),
            "rag_stats": rag_stats,
            "config": {
                "model": settings.openai_model,
                "collection": settings.collection_name
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Document Management ====================

@app.post("/ingest-document", response_model=dict)
async def ingest_document(request: DocumentRequest):
    """
    Ingest a document into the vector store
    
    Request body:
        - content: Document text content
        - document_name: Optional name for the document
        - metadata: Optional metadata dictionary
    """
    try:
        document_id = f"doc_{uuid.uuid4().hex[:8]}"
        
        result = rag_service.ingest_document(
            document_id=document_id,
            content=request.content,
            document_name=request.document_name,
            metadata=request.metadata
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "document_name": request.document_name,
            "message": "Document ingested successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest-document-file")
async def ingest_document_file(file: UploadFile = File(...), document_name: str = "uploaded_document"):
    """
    Ingest a document from file upload
    Supports .txt and .pdf files (basic text extraction)
    """
    try:
        content = await file.read()
        
        # Simple text extraction for .txt files
        if file.filename.endswith(".txt"):
            text_content = content.decode("utf-8")
        else:
            raise HTTPException(
                status_code=400,
                detail="Only .txt files supported in MVP. Use /ingest-document for direct text."
            )
        
        document_id = f"doc_{uuid.uuid4().hex[:8]}"
        
        result = rag_service.ingest_document(
            document_id=document_id,
            content=text_content,
            document_name=document_name,
            metadata={"source": "file_upload", "filename": file.filename}
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "document_name": document_name,
            "message": "Document file ingested successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Content Generation ====================

@app.post("/generate-content", response_model=GeneratedContent)
async def generate_content(request: PromptRequest):
    """
    Generate content based on a prompt using RAG + LLM
    
    Request body:
        - prompt: User prompt/request
        - context_retrieval_k: Number of documents to retrieve (default: 3)
        - template_placeholders: Optional list of placeholders to fill
    """
    try:
        # Retrieve relevant context from stored documents
        documents, metadatas = rag_service.retrieve_context(
            query=request.prompt,
            k=request.context_retrieval_k
        )
        
        # Format context
        context = rag_service.format_context(documents, metadatas)
        
        # Generate content using LLM
        generated_text = llm_service.generate_content(
            prompt=request.prompt,
            context=context if context else None
        )
        
        # Prepare response
        response_data = {
            "content": generated_text,
            "sources": [meta.get("document_name", "Unknown") for meta in metadatas] if metadatas else None
        }
        
        # If template placeholders specified, parse content into structured data
        if request.template_placeholders:
            template_data = _parse_content_to_placeholders(
                generated_text,
                request.template_placeholders
            )
            response_data["template_data"] = template_data
        
        return GeneratedContent(**response_data)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_content_to_placeholders(content: str, placeholders: list) -> dict:
    """
    Simple parser to map generated content to placeholders
    For MVP, uses simple section-based mapping
    """
    result = {}
    sections = content.split("\n\n")
    
    for i, placeholder in enumerate(placeholders):
        if i < len(sections):
            result[placeholder] = sections[i]
        else:
            result[placeholder] = ""
    
    return result


# ==================== Template Operations ====================

@app.post("/find-placeholders")
async def find_placeholders(template_path: str):
    """
    Find all placeholders in a Word template
    Placeholders should be in format: {{PLACEHOLDER_NAME}}
    """
    try:
        placeholders = template_engine.find_placeholders(template_path)
        return {
            "template_path": template_path,
            "placeholders_found": placeholders,
            "count": len(placeholders)
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Template file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/populate-template")
async def populate_template(request: TemplatePopulationRequest):
    """
    Populate a Word template with provided data
    
    Request body:
        - template_path: Path to .docx template file
        - placeholders_data: Dictionary of placeholder -> value mappings
        - output_path: Optional output path (defaults to template_populated.docx)
    """
    try:
        output_path = template_engine.populate_template(
            template_path=request.template_path,
            placeholders_data=request.placeholders_data,
            output_path=request.output_path
        )
        
        return {
            "status": "success",
            "output_path": output_path,
            "message": "Template populated successfully"
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Workflow Operations ====================

@app.post("/end-to-end-generation")
async def end_to_end_generation(
    prompt: str,
    template_path: str,
    output_path: str = None
):
    """
    Complete end-to-end workflow:
    1. Generate content from prompt using RAG
    2. Find placeholders in template
    3. Map content to placeholders
    4. Populate and save document
    """
    try:
        # Step 1: Find placeholders
        placeholders = template_engine.find_placeholders(template_path)
        
        # Step 2: Generate content with placeholder context
        request = PromptRequest(
            prompt=prompt,
            context_retrieval_k=3,
            template_placeholders=placeholders
        )
        
        generation_response = await generate_content(request)
        template_data = generation_response.template_data or generation_response.content
        
        # Handle case where content isn't structured
        if isinstance(template_data, str):
            # Simple fallback: use content for all placeholders
            template_data = {ph: generation_response.content for ph in placeholders}
        
        # Step 3: Populate template
        populated_path = template_engine.populate_template(
            template_path=template_path,
            placeholders_data=template_data,
            output_path=output_path
        )
        
        return {
            "status": "success",
            "generated_content": generation_response.content,
            "sources": generation_response.sources,
            "populated_document": populated_path,
            "placeholders_filled": len(placeholders)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Server Entry Point ====================

if __name__ == "__main__":
    import uvicorn
    
    print(f"""
    ╔════════════════════════════════════════════╗
    ║  Word Template + LLM + RAG API Starting     ║
    ╠════════════════════════════════════════════╣
    ║  Server: http://{settings.server_host}:{settings.server_port}
    ║  Docs: http://{settings.server_host}:{settings.server_port}/docs
    ║  Model: {settings.openai_model}
    ║  Collection: {settings.collection_name}
    ╚════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "backend.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True
    )
