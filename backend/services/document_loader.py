"""Extract plain text from uploaded files (.txt, .md, .docx, .pdf)."""

import io
from pathlib import Path

SUPPORTED_EXTENSIONS = (".txt", ".md", ".docx", ".pdf")


class UnsupportedFileType(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    extension = Path(filename or "").suffix.lower()

    if extension in (".txt", ".md"):
        for encoding in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    if extension == ".docx":
        return _docx_text(data)

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)

    raise UnsupportedFileType(
        f"Unsupported file type '{extension or filename}'. "
        f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
    )


def _docx_text(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    lines = []
    # Walk the body in document order so tables stay next to their headings.
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            if block.text.strip():
                lines.append(block.text)
        elif isinstance(block, Table):
            for row in block.rows:
                seen, cells = set(), []
                for cell in row.cells:  # merged cells repeat; keep one copy
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        cells.append(cell.text.strip())
                if any(cells):
                    lines.append(" | ".join(cells))
    return "\n".join(lines)
