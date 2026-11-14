"""Template engine: find and fill `{{PLACEHOLDER}}` tokens in .docx files.

Word frequently splits a token like `{{TITLE}}` across several runs
(`{{`, `TITLE`, `}}`). Replacement therefore works on the joined text of a
paragraph and writes the result back into the run where the token starts, so
the surrounding formatting (and the token's own formatting) is preserved.

Covered: body paragraphs, tables (including nested), text boxes, headers and
footers.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from backend.config import settings

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_][A-Za-z0-9_ .\-]*?)\s*\}\}")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.\- ]+")


class TemplateEngine:
    # ------------------------------------------------------------ file paths
    @staticmethod
    def _safe_name(name: str) -> str:
        """Reduce a user-supplied path to a bare .docx file name."""
        base = Path(str(name).replace("\\", "/")).name
        base = _SAFE_NAME_RE.sub("_", base).strip(" .")
        if not base:
            raise ValueError("Invalid file name.")
        if not base.lower().endswith(".docx"):
            base += ".docx"
        return base

    def resolve_template(self, name: str) -> Path:
        """Map a template name to a file inside the templates directory."""
        path = settings.templates_path / self._safe_name(name)
        if not path.is_file():
            raise FileNotFoundError(f"Template not found: {path.name}")
        return path

    def list_templates(self) -> List[dict]:
        directory = settings.templates_path
        if not directory.is_dir():
            return []
        return [
            {"name": p.name, "placeholders": self.find_placeholders(p)}
            for p in sorted(directory.glob("*.docx"))
            if not p.name.startswith("~$")
        ]

    def save_template(self, filename: str, data: bytes) -> Path:
        name = self._safe_name(filename)
        settings.templates_path.mkdir(parents=True, exist_ok=True)
        path = settings.templates_path / name
        path.write_bytes(data)
        try:
            Document(str(path))  # reject files that are not real .docx
        except Exception:
            path.unlink(missing_ok=True)
            raise ValueError("File is not a valid .docx document.")
        return path

    def resolve_output(self, name: str) -> Path:
        path = settings.output_path / self._safe_name(name)
        if not path.is_file():
            raise FileNotFoundError(f"Generated file not found: {path.name}")
        return path

    # ------------------------------------------------------------- traversal
    @staticmethod
    def _iter_paragraphs(doc) -> Iterator[Paragraph]:
        roots = [(doc.element.body, doc)]
        for rel in doc.part.rels.values():
            if not rel.is_external and rel.reltype in (RT.HEADER, RT.FOOTER):
                roots.append((rel.target_part.element, rel.target_part))
        for root, parent in roots:
            for p in root.iter(qn("w:p")):
                yield Paragraph(p, parent)

    @staticmethod
    def _paragraph_text(paragraph: Paragraph) -> str:
        return "".join(run.text for run in paragraph.runs)

    # ------------------------------------------------------------------ find
    def find_placeholders(self, source) -> List[str]:
        """Placeholder names in document order, without duplicates.

        `source` is a path or a binary file-like object.
        """
        doc = Document(str(source) if isinstance(source, Path) else source)
        found: Dict[str, None] = {}
        for paragraph in self._iter_paragraphs(doc):
            text = self._paragraph_text(paragraph)
            if "{{" in text:
                for name in PLACEHOLDER_RE.findall(text):
                    found.setdefault(name, None)
        return list(found)

    # -------------------------------------------------------------- populate
    def populate_template(
        self,
        template_path,
        placeholders_data: Dict[str, str],
        output_path: Optional[str] = None,
    ) -> Tuple[Path, dict]:
        """Fill a template and save it in the output directory.

        Returns the output path and a report with `filled` and `missing`
        placeholder names.
        """
        template = Path(template_path)
        if not template.is_file():
            raise FileNotFoundError(f"Template not found: {template.name}")

        doc = Document(str(template))
        data = {str(k).strip(): "" if v is None else str(v) for k, v in placeholders_data.items()}
        filled, missing = {}, {}
        for paragraph in self._iter_paragraphs(doc):
            self._replace_in_paragraph(paragraph, data, filled, missing)

        if output_path:
            name = self._safe_name(output_path)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"{template.stem}_{stamp}.docx"
        settings.output_path.mkdir(parents=True, exist_ok=True)
        destination = settings.output_path / name
        doc.save(str(destination))
        return destination, {"filled": list(filled), "missing": list(missing)}

    def _replace_in_paragraph(self, paragraph, data, filled, missing) -> None:
        position = 0
        while True:
            runs = paragraph.runs
            text = "".join(run.text for run in runs)
            match = PLACEHOLDER_RE.search(text, position)
            if not match:
                return
            name = match.group(1)
            if name not in data:
                missing.setdefault(name, None)
                position = match.end()
                continue

            replacement = data[name]
            self._splice(runs, match.start(), match.end(), replacement)
            filled.setdefault(name, None)
            # Continue after the inserted text so a value that itself contains
            # "{{...}}" is never re-expanded.
            position = match.start() + len(replacement)

    @staticmethod
    def _splice(runs, start: int, end: int, replacement: str) -> None:
        """Replace characters [start, end) of the joined run text."""
        offset, first = 0, True
        for run in runs:
            run_text = run.text
            run_start, run_end = offset, offset + len(run_text)
            offset = run_end
            if run_end <= start or run_start >= end:
                continue
            before = run_text[: max(0, start - run_start)]
            after = run_text[max(0, end - run_start):]
            if first:
                # "\n" in the value becomes a line break inside the run.
                run.text = before + replacement + after
                first = False
            else:
                run.text = after


template_engine = TemplateEngine()
