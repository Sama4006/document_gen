# DocGen: Word templates + LLM + RAG

Generate Word documents with an LLM that is grounded in your own source
material. A FastAPI backend handles retrieval (ChromaDB), generation (OpenAI)
and `.docx` template filling; a Word add-in puts it all in a task pane.

```
Word add-in (task pane)  ──►  FastAPI backend
                               ├─ RAG service      chunk → embed → ChromaDB
                               ├─ LLM service      OpenAI chat + embeddings
                               └─ Template engine  {{PLACEHOLDER}} → .docx
```

## Quick start

Requires Python 3.10+ and an OpenAI API key.

```bash
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

cp .env.example .env                # then put your key in OPENAI_API_KEY
python run.py                       # or, on a Mac, double-click start_server.command
```

`RELOAD=1 python run.py` restarts the server automatically when the code or
`.env` changes.

- API docs (Swagger): http://localhost:8000/docs
- Task pane in a browser: http://localhost:8000/addin/taskpane.html

Seven example templates are in `templates/`. Regenerate them with
`python create_templates.py` and `python create_sample_template.py`.

## How it works

1. **Knowledge base.** Text, `.txt`, `.md`, `.docx` or `.pdf` files are split
   into overlapping passages, embedded with the OpenAI embedding model and
   stored in a local ChromaDB collection (`./chroma_data`).
2. **Generation.** A prompt is embedded, the closest passages are retrieved
   and passed to the chat model as context.
3. **Templates.** Any `.docx` containing `{{PLACEHOLDER}}` tokens is a
   template. The model returns one value per placeholder as JSON, and the
   engine writes the values into the document, keeping the formatting of the
   text around (and of) each token. Tokens in tables, text boxes, headers and
   footers are handled, as are tokens Word has split across runs.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness; reports a missing API key. No OpenAI call. |
| GET | `/status` | Counts and config. `?check_llm=true` tests the OpenAI key. |
| POST | `/ingest-document` | Add raw text to the knowledge base |
| POST | `/ingest-document-file` | Add a `.txt` / `.md` / `.docx` / `.pdf` file (multipart) |
| GET | `/documents` | List ingested documents |
| DELETE | `/documents/{id}` | Remove a document |
| POST | `/generate-content` | Free-form content with RAG context |
| POST | `/fill-placeholders` | One generated value per placeholder name |
| GET | `/templates` | Server templates and their placeholders |
| POST | `/templates` | Upload a `.docx` template (multipart) |
| POST | `/find-placeholders?template_path=…` | Placeholders in one template |
| POST | `/populate-template` | Fill a template with values you supply |
| POST | `/end-to-end-generation` | Prompt + template → finished document |
| GET | `/download/{filename}` | Download a generated document |

Examples:

```bash
# 1. Add source material
curl -X POST localhost:8000/ingest-document -H 'Content-Type: application/json' \
  -d '{"content": "Q1 revenue grew 18% to ₹4.2M…", "document_name": "Q1 finance"}'

curl -X POST localhost:8000/ingest-document-file -F file=@report.pdf

# 2. Prompt + template -> document
curl -X POST localhost:8000/end-to-end-generation -H 'Content-Type: application/json' \
  -d '{"prompt": "Write the Q1 business report",
       "template_path": "report_template.docx",
       "known_values": {"AUTHOR": "Satyam", "DATE": "14 Nov 2026"}}'

# 3. Download the result (name comes from the previous response)
curl -OJ localhost:8000/download/report_template_20261114_120000.docx
```

Templates are addressed by file name inside `TEMPLATES_DIR`; generated files
are written to `OUTPUT_DIR`. Paths outside those folders are not accepted.

## Word add-in

The backend serves the task pane itself at `/addin/`, so there is no second
server to run. Word only loads add-ins over HTTPS, so create a trusted local
certificate once (needs Node.js):

```bash
npx office-addin-dev-certs install
python run.py          # now starts on https://localhost:8000
```

Then sideload `frontend/word-plugin/manifest.xml`:

- **Word on the web:** Home → Add-ins → More Add-ins → My Add-ins → Upload My
  Add-in → choose `manifest.xml`.
- **Windows:** put `manifest.xml` in a shared folder, add that folder under
  File → Options → Trust Center → Trust Center Settings → Trusted Add-in
  Catalogs, restart Word, then Home → Add-ins → Shared Folder.
- **Mac:** copy `manifest.xml` to
  `~/Library/Containers/com.microsoft.Word/Data/Documents/wef/` and restart
  Word.

An **AI Generator** button appears on the Home tab. The pane has four tabs:

- **Knowledge**: paste text, upload a file, or add the open document.
- **Generate**: write content from a prompt and insert it at the cursor.
- **Template**: find `{{PLACEHOLDER}}` tokens in the open document, fill them
  by hand or with AI, and apply; or generate a whole document from a server
  template and open it in Word.
- **⚙**: backend URL and API key.

To host it elsewhere, replace `https://localhost:8000` in `manifest.xml` with
your server's HTTPS URL.

## Deploy to Vercel

The app runs on Vercel as a single Python function. Vercel's disk is wiped
between requests, so the knowledge base lives in **Upstash Vector** there
(free tier available), and generated documents are returned directly in the
API response.

1. **Import the repository** in Vercel (Add New → Project → pick this repo).
   `pyproject.toml` and `vercel.json` already configure it; no build settings
   need changing.
2. **Add Upstash Vector**: in the Vercel project open *Storage* (or the
   Marketplace), add **Upstash → Vector**, and create an index with
   **dimension 1536** and metric **COSINE**. Connecting it to the project
   adds `UPSTASH_VECTOR_REST_URL` and `UPSTASH_VECTOR_REST_TOKEN`. If you
   create the index on upstash.com instead, add those two variables yourself.
3. **Add environment variables** (Settings → Environment Variables), the same
   values as your `.env`:

   | Variable | Example |
   |---|---|
   | `OPENAI_API_KEY` | your Gemini or OpenAI key |
   | `OPENAI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` (Gemini) |
   | `OPENAI_MODEL` | `gemini-3.8-flash` |
   | `OPENAI_FALLBACK_MODELS` | `gemini-3.1-flash-lite,gemini-flash-latest` |
   | `OPENAI_EMBEDDING_MODEL` | `gemini-embedding-001` |
   | `MAX_OUTPUT_TOKENS` | `8000` |
   | `API_KEY` | any long random string (strongly recommended, see below) |

4. **Redeploy** so the variables take effect, then open
   `https://<your-app>.vercel.app/status?check_llm=true`.

**Protect it.** A public deployment spends your API quota for anyone who finds
the URL. Set `API_KEY`, then enter the same value in the add-in's ⚙ tab (or
send it as the `X-API-Key` header).

**Word add-in from Vercel.** Vercel serves HTTPS, so no certificates are
needed: download `https://<your-app>.vercel.app/addin/manifest.xml` (it is
generated with your deployment's address) and sideload it as described above.

**On Vercel:**
- Templates uploaded through the API or the add-in are temporary. To keep a
  template, add it to the `templates/` folder in the repository.
- The embedding size is matched to the Upstash index automatically. If you
  change the embedding model later, create a new index (or reset it) and
  re-ingest your documents.

## Configuration

All settings live in `.env` (see `.env.example`).

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | none | Required for generation and ingestion |
| `OPENAI_MODEL` | `gpt-5.6-terra` | Any chat-completions model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Changing it later requires re-ingesting |
| `OPENAI_BASE_URL` | none | Other OpenAI-compatible endpoints |
| `API_KEY` | none | If set, clients must send `X-API-Key` |
| `CORS_ORIGINS` | `*` | Restrict in production |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `1200` / `200` | Characters per passage |
| `TEMPLATES_DIR` / `OUTPUT_DIR` | `./templates` / `./output` | |
| `CHROMA_DB_PATH` | `./chroma_data` | Delete the folder to reset the knowledge base |
| `UPSTASH_VECTOR_REST_URL` / `_TOKEN` | none | If set, the knowledge base is stored in Upstash Vector instead of ChromaDB |
| `OPENAI_FALLBACK_MODELS` | none | Models tried in order when the main one is busy or unavailable |
| `OPENAI_TIMEOUT` | `60` | Seconds to wait for one API response |

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests replace OpenAI with fakes, so they need no key and no network.

## Docker

```bash
docker compose up --build
```

Data (vector store and generated files) is kept in the `docgen-data` volume.

## Project layout

```
backend/
  main.py                  FastAPI app and routes
  config.py                Settings from .env
  models/schemas.py        Request/response models
  services/
    llm_service.py         OpenAI chat + embeddings
    rag_service.py         Chunking, ChromaDB storage, retrieval
    document_loader.py     Text extraction (.txt/.md/.docx/.pdf)
    template_engine.py     Placeholder search and replacement
frontend/word-plugin/      Task pane (HTML/CSS/JS), manifest, icons
templates/                 Example .docx templates
tests/                     pytest suite
run.py                     Starts the server (HTTPS if certificates exist)
```

## Troubleshooting

- **"OPENAI_API_KEY is not set"**: add the key to `.env` and restart.
- **"OpenAI error: …model…"**: your key cannot use `OPENAI_MODEL`; set a
  model that it can.
- **Add-in pane is blank in Word**: the server is not on HTTPS, or the
  certificate is not trusted. Re-run `npx office-addin-dev-certs install`.
- **Scanned PDF gives "No text could be extracted"**: it has no text layer;
  run OCR first.
- **Changed the embedding model**: delete `chroma_data/` and ingest again.
