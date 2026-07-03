# Word Template + LLM + RAG Application

A minimalist AI-powered Word document generation system using FastAPI, ChromaDB (RAG), and OpenAI LLM.

## Architecture

```
Frontend (Word Plugin)
    ↓
FastAPI Backend
├── LLM Service (OpenAI GPT-4)
├── RAG Service (ChromaDB + Vector Embeddings)
└── Template Engine (Word Population)
    ↓
Generated & Populated Word Documents
```

## Quick Start

### 1. Backend Setup

#### Prerequisites
- Python 3.8+
- OpenAI API key ([Get here](https://platform.openai.com/api-keys))

#### Installation

```bash
# Navigate to project root
cd "/Users/shubhamsaini/Desktop/Genai Project"

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Setup environment variables
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

#### Run Server

```bash
# From project root
python -m uvicorn backend.main:app --reload

# Server will start at http://localhost:8000
# API Docs available at http://localhost:8000/docs
```

### 2. API Endpoints

#### Health Check
```bash
GET /health
```

#### Ingest Document
```bash
POST /ingest-document
Content-Type: application/json

{
  "content": "Your document text here",
  "document_name": "example_doc",
  "metadata": {"source": "user"}
}
```

#### Generate Content
```bash
POST /generate-content
Content-Type: application/json

{
  "prompt": "Write an executive summary",
  "context_retrieval_k": 3,
  "template_placeholders": ["SUMMARY", "KEY_POINTS"]
}
```

#### Populate Word Template
```bash
POST /populate-template
Content-Type: application/json

{
  "template_path": "./templates/sample_template.docx",
  "placeholders_data": {
    "TITLE": "My Document",
    "SUMMARY": "Generated summary here",
    "DATE": "2026-06-26"
  },
  "output_path": "./output/final_document.docx"
}
```

#### End-to-End Workflow
```bash
POST /end-to-end-generation?prompt=Write+a+report&template_path=./templates/sample_template.docx
```

### 3. Template Format

Templates use `{{PLACEHOLDER_NAME}}` format:

```
Document Title: {{TITLE}}

Summary: {{SUMMARY}}

Key Points: {{KEY_POINTS}}

Date: {{DATE}}
```

## Folder Structure

```
Genai Project/
├── backend/
│   ├── main.py                 # FastAPI app
│   ├── config.py              # Configuration
│   ├── requirements.txt        # Dependencies
│   ├── services/
│   │   ├── llm_service.py     # OpenAI integration
│   │   ├── rag_service.py     # ChromaDB RAG
│   │   └── template_engine.py # Word population
│   ├── models/
│   │   └── schemas.py         # Pydantic models
│   └── __init__.py
├── frontend/
│   └── word-plugin/           # Office Add-in (coming next)
├── templates/
│   └── sample_template.docx   # Example template
├── .env.example               # Configuration template
└── README.md                  # This file
```

## Key Features

### 1. **LLM Service** (OpenAI Integration)
- Content generation with context awareness
- Text embedding support
- Temperature & token control

### 2. **RAG Service** (ChromaDB)
- Document ingestion and storage
- Vector similarity search
- Semantic context retrieval
- Metadata support

### 3. **Template Engine** (Word Population)
- Placeholder detection in .docx files
- Smart text replacement
- Formatting preservation
- Batch operations

## Next Steps

1. **Test Backend**
   - Use Swagger UI at http://localhost:8000/docs
   - Upload documents and generate content

2. **Build Word Plugin**
   - Create Office Add-in UI
   - Connect to FastAPI backend
   - Provide user-friendly interface

3. **Deploy**
   - Package backend (Docker)
   - Deploy Word plugin to Microsoft AppSource
   - Setup production infrastructure

## Troubleshooting

### "OpenAI API Key Invalid"
- Verify key in .env file
- Check key has correct permissions
- Generate new key if needed

### ChromaDB Errors
- Clear `./chroma_data` directory
- Restart server
- Check disk space

### Template Placeholders Not Found
- Verify placeholder format: `{{NAME}}`
- Check if placeholders are in separate runs in Word
- Use `/find-placeholders` endpoint to debug

## Development Notes

- **LLM Selection**: Currently using gpt-4, can switch to gpt-4-turbo or gpt-3.5-turbo
- **Vector DB**: ChromaDB chosen for zero-setup MVP (no external DB needed)
- **Embeddings**: OpenAI text-embedding-3-small (efficient & accurate)

## Future Enhancements

- [ ] PDF document support
- [ ] Custom prompt templates
- [ ] Multi-document RAG chains
- [ ] Word plugin UI
- [ ] Document history/versioning
- [ ] Webhook support for async operations
- [ ] Rate limiting & authentication
- [ ] Prompt caching for cost reduction
