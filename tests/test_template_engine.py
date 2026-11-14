from docx import Document

from backend.services.template_engine import template_engine

DATA = {
    "TITLE": "Q1 Report",
    "AUTHOR": "Asha",
    "DATE": "2026-11-14",
    "SUMMARY": "Line one\nLine two with {{TITLE}} kept literally",
    "STATUS": "On track",
}


def all_text(path):
    doc = Document(str(path))
    return "\n".join(p.text for p in template_engine._iter_paragraphs(doc))


def test_find_placeholders_handles_split_runs_tables_and_headers(template):
    assert template_engine.find_placeholders(template) == [
        "TITLE", "AUTHOR", "DATE", "SUMMARY", "NOT_PROVIDED", "STATUS",
    ]


def test_populate_replaces_everywhere(template):
    output, report = template_engine.populate_template(template, DATA, "out.docx")
    text = all_text(output)

    assert "Prepared by Asha on 2026-11-14." in text
    assert "Confidential - Q1 Report" in text  # header
    assert "On track" in text  # table cell
    assert report["filled"] == ["TITLE", "AUTHOR", "DATE", "SUMMARY", "STATUS"]
    assert report["missing"] == ["NOT_PROVIDED"]
    assert "{{NOT_PROVIDED}}" in text  # unknown tokens are left alone


def test_populate_preserves_formatting_and_line_breaks(template):
    output, _ = template_engine.populate_template(template, DATA, "out.docx")
    doc = Document(str(output))

    author_par = next(p for p in doc.paragraphs if "Asha" in p.text)
    assert author_par.runs[0].bold and author_par.runs[0].text == "Prepared by "
    author_run = next(r for r in author_par.runs if "Asha" in r.text)
    assert author_run.italic and not author_run.bold

    summary = next(p for p in doc.paragraphs if p.text.startswith("Line one"))
    assert summary.text.count("\n") == 1  # newline became a Word line break
    assert len(summary._p.xpath(".//w:br")) == 1
    # A value containing {{TITLE}} must not be expanded a second time.
    assert "{{TITLE}} kept literally" in summary.text


def test_paths_cannot_escape_directories(template):
    assert template_engine._safe_name("../../etc/passwd") == "passwd.docx"
    assert template_engine._safe_name("..\\..\\secret.docx") == "secret.docx"
    output, _ = template_engine.populate_template(template, DATA, "../../evil.docx")
    assert output.parent.name == "output" and output.name == "evil.docx"
