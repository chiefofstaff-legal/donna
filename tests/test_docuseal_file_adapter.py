"""
Goodhart-proof tests for lib/docuseal_file_adapter.py.

Coverage targets:
  - detect_format on all 10 formats with correct AND wrong-extension+magic cases
  - can_passthrough for every format
  - _convert_md_to_html with full Markdown surface (headings/para/list/code/link)
  - png_to_pdf and jpg_to_pdf with synthetic PIL fixtures
  - txt_to_pdf (both reportlab and minimal paths)
  - unavailable libreoffice → plain-language error
  - round-trip: convert → detect_format on output → assert correct format
  - mutation-testable: assertions verify values, not call counts
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp(suffix: str = "") -> Path:
    """Return a Path to a new temp file (not yet created)."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    return Path(f.name)


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def _pdf_magic() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n"


def _docx_magic() -> bytes:
    """Minimal valid DOCX (ZIP with word/ entry)."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _odt_magic() -> bytes:
    """Minimal valid ODT (ZIP with mimetype entry)."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", "<office:document/>")
    return buf.getvalue()


def _png_magic() -> bytes:
    try:
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except ImportError:
        # Minimal valid 1×1 PNG (hard-coded)
        return (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
            b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
            b"\x00\x00IEND\xaeB`\x82"
        )


def _jpg_magic() -> bytes:
    try:
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1), color=(0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        return buf.getvalue()
    except ImportError:
        # Minimal JFIF stub — valid magic, not a complete image
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"


# Magic byte constants for formats without PIL fallback
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8
_RTF_MAGIC = b"{\\rtf1\\ansi\nHello RTF}"


# ---------------------------------------------------------------------------
# detect_format — correct extension + magic
# ---------------------------------------------------------------------------

class TestDetectFormatCorrectExtension:
    def test_pdf(self, tmp_path):
        p = tmp_path / "doc.pdf"
        p.write_bytes(_pdf_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "pdf"

    def test_docx(self, tmp_path):
        p = tmp_path / "doc.docx"
        p.write_bytes(_docx_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "docx"

    def test_doc(self, tmp_path):
        p = tmp_path / "doc.doc"
        p.write_bytes(_OLE2_MAGIC)
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "doc"

    def test_rtf(self, tmp_path):
        p = tmp_path / "doc.rtf"
        p.write_bytes(_RTF_MAGIC)
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "rtf"

    def test_odt(self, tmp_path):
        p = tmp_path / "doc.odt"
        p.write_bytes(_odt_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "odt"

    def test_html(self, tmp_path):
        p = tmp_path / "doc.html"
        p.write_bytes(b"<!DOCTYPE html><html><body>hello</body></html>")
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "html"

    def test_md(self, tmp_path):
        p = tmp_path / "doc.md"
        p.write_text("# Hello", encoding="utf-8")
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "md"

    def test_png(self, tmp_path):
        p = tmp_path / "doc.png"
        p.write_bytes(_png_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "png"

    def test_jpg(self, tmp_path):
        p = tmp_path / "doc.jpg"
        p.write_bytes(_jpg_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "jpg"

    def test_txt(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("Hello world", encoding="utf-8")
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "txt"


# ---------------------------------------------------------------------------
# detect_format — WRONG extension, correct magic bytes
# Proves we do not trust extension alone.
# ---------------------------------------------------------------------------

class TestDetectFormatWrongExtension:
    """Each test saves a file with a misleading .xyz extension but real magic."""

    def test_pdf_disguised_as_txt(self, tmp_path):
        p = tmp_path / "sneaky.txt"
        p.write_bytes(_pdf_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "pdf"

    def test_docx_disguised_as_pdf(self, tmp_path):
        p = tmp_path / "sneaky.pdf"
        p.write_bytes(_docx_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "docx"

    def test_doc_disguised_as_docx(self, tmp_path):
        p = tmp_path / "sneaky.docx"
        p.write_bytes(_OLE2_MAGIC)
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "doc"

    def test_rtf_disguised_as_txt(self, tmp_path):
        p = tmp_path / "sneaky.txt"
        p.write_bytes(_RTF_MAGIC)
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "rtf"

    def test_odt_disguised_as_docx(self, tmp_path):
        p = tmp_path / "sneaky.docx"
        p.write_bytes(_odt_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "odt"

    def test_png_disguised_as_jpg(self, tmp_path):
        p = tmp_path / "sneaky.jpg"
        p.write_bytes(_png_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "png"

    def test_jpg_disguised_as_png(self, tmp_path):
        p = tmp_path / "sneaky.png"
        p.write_bytes(_jpg_magic())
        from lib.docuseal_file_adapter import detect_format
        assert detect_format(p) == "jpg"


# ---------------------------------------------------------------------------
# can_passthrough
# ---------------------------------------------------------------------------

class TestCanPassthrough:
    @pytest.mark.parametrize("fmt", ["pdf", "docx", "html"])
    def test_passthrough_formats(self, fmt):
        from lib.docuseal_file_adapter import can_passthrough
        assert can_passthrough(fmt) is True

    @pytest.mark.parametrize("fmt", ["doc", "rtf", "odt", "md", "png", "jpg", "txt"])
    def test_non_passthrough_formats(self, fmt):
        from lib.docuseal_file_adapter import can_passthrough
        assert can_passthrough(fmt) is False


# ---------------------------------------------------------------------------
# Markdown → HTML conversion
# ---------------------------------------------------------------------------

MD_SAMPLE = """\
# Main heading

## Sub heading

A paragraph with **bold**, *italic*, and `inline code` text.

- First item
- Second item with a [link](https://example.com)

```
def hello():
    return "world"
```

Trailing paragraph.
"""


class TestMdToHtml:
    def _convert(self, tmp_path: Path) -> str:
        from lib.docuseal_file_adapter import _convert_md_to_html
        src = tmp_path / "doc.md"
        src.write_text(MD_SAMPLE, encoding="utf-8")
        out = _convert_md_to_html(src, tmp_path)
        return out.read_text(encoding="utf-8")

    def test_output_file_is_html(self, tmp_path):
        from lib.docuseal_file_adapter import _convert_md_to_html
        src = tmp_path / "doc.md"
        src.write_text(MD_SAMPLE, encoding="utf-8")
        out = _convert_md_to_html(src, tmp_path)
        assert out.suffix == ".html"

    def test_contains_h1(self, tmp_path):
        html = self._convert(tmp_path)
        assert "<h1>" in html and "Main heading" in html

    def test_contains_h2(self, tmp_path):
        html = self._convert(tmp_path)
        assert "<h2>" in html and "Sub heading" in html

    def test_contains_paragraph(self, tmp_path):
        html = self._convert(tmp_path)
        assert "Trailing paragraph" in html

    def test_contains_list_item(self, tmp_path):
        html = self._convert(tmp_path)
        assert "<li>" in html and "First item" in html

    def test_contains_code_block(self, tmp_path):
        html = self._convert(tmp_path)
        assert "hello" in html

    def test_contains_link(self, tmp_path):
        html = self._convert(tmp_path)
        assert "https://example.com" in html

    def test_html_doctype_present(self, tmp_path):
        html = self._convert(tmp_path)
        assert html.lower().startswith("<!doctype html>")

    def test_minimal_renderer_fallback(self, tmp_path):
        """Force the minimal stdlib renderer by masking the markdown package."""
        with patch.dict("sys.modules", {"markdown": None}):
            from importlib import reload
            import lib.docuseal_file_adapter as mod
            reload(mod)
            src = tmp_path / "doc.md"
            src.write_text("# Title\n\nParagraph.\n\n- item\n", encoding="utf-8")
            out = mod._convert_md_to_html(src, tmp_path)
            html = out.read_text(encoding="utf-8")
            assert "<h1>" in html
            assert "<li>" in html
            assert "Paragraph" in html


# ---------------------------------------------------------------------------
# PNG / JPG → PDF
# ---------------------------------------------------------------------------

class TestImageToPdf:
    def _make_png(self, tmp_path: Path) -> Path:
        p = tmp_path / "img.png"
        p.write_bytes(_png_magic())
        return p

    def _make_jpg(self, tmp_path: Path) -> Path:
        p = tmp_path / "img.jpg"
        p.write_bytes(_jpg_magic())
        return p

    @pytest.mark.skipif(
        not shutil.which("python3"),  # always True, just a hook
        reason="PIL required"
    )
    def test_png_to_pdf_output_starts_with_pdf_magic(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        p = tmp_path / "img.png"
        p.write_bytes(buf.getvalue())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        from lib.docuseal_file_adapter import _convert_png_to_pdf
        out = _convert_png_to_pdf(p, out_dir)
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_jpg_to_pdf_output_starts_with_pdf_magic(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        p = tmp_path / "img.jpg"
        p.write_bytes(buf.getvalue())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        from lib.docuseal_file_adapter import _convert_jpg_to_pdf
        out = _convert_jpg_to_pdf(p, out_dir)
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_png_to_pdf_round_trip_format(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        import io
        img = Image.new("RGB", (2, 2))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        p = tmp_path / "img.png"
        p.write_bytes(buf.getvalue())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        from lib.docuseal_file_adapter import _convert_png_to_pdf, detect_format
        out = _convert_png_to_pdf(p, out_dir)
        assert detect_format(out) == "pdf"

    def test_image_to_pdf_missing_pillow(self, tmp_path):
        from lib.docuseal_file_adapter import AdapterError
        p = tmp_path / "img.png"
        p.write_bytes(_png_magic())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            from importlib import reload
            import lib.docuseal_file_adapter as mod
            reload(mod)
            with pytest.raises(mod.AdapterError, match="Pillow"):
                mod._image_to_pdf(p, out_dir)


# ---------------------------------------------------------------------------
# TXT → PDF
# ---------------------------------------------------------------------------

class TestTxtToPdf:
    def _make_txt(self, tmp_path: Path, content: str = "") -> Path:
        p = tmp_path / "doc.txt"
        text = content or (
            "First paragraph with enough words to test wrapping.\n\n"
            "Second paragraph.\n\n"
            "Third paragraph that has a very long line indeed for testing purposes "
            "and wrapping behaviour across the page width.\n"
        )
        p.write_text(text, encoding="utf-8")
        return p

    def test_output_is_valid_pdf_magic(self, tmp_path):
        from lib.docuseal_file_adapter import _convert_txt_to_pdf
        src = self._make_txt(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        out = _convert_txt_to_pdf(src, out_dir)
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_output_round_trip_format(self, tmp_path):
        from lib.docuseal_file_adapter import _convert_txt_to_pdf, detect_format
        src = self._make_txt(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        out = _convert_txt_to_pdf(src, out_dir)
        assert detect_format(out) == "pdf"

    def test_minimal_pdf_writer_produces_valid_pdf(self, tmp_path):
        """Force the stdlib minimal path even if reportlab is installed."""
        from lib.docuseal_file_adapter import _txt_to_pdf_minimal
        out = tmp_path / "minimal.pdf"
        _txt_to_pdf_minimal("Hello\n\nWorld", out)
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_minimal_pdf_multipage(self, tmp_path):
        """Many lines should produce a multi-page PDF that's still valid."""
        from lib.docuseal_file_adapter import _txt_to_pdf_minimal
        out = tmp_path / "long.pdf"
        many_lines = "\n".join(f"Line {i}" for i in range(200))
        _txt_to_pdf_minimal(many_lines, out)
        content = out.read_bytes()
        assert content[:5] == b"%PDF-"
        assert b"%%EOF" in content


# ---------------------------------------------------------------------------
# Unavailable libreoffice → plain-language error
# ---------------------------------------------------------------------------

class TestLibreofficeUnavailable:
    def test_doc_raises_plain_language_error(self, tmp_path):
        from lib.docuseal_file_adapter import AdapterError, _convert_doc_to_docx
        p = tmp_path / "doc.doc"
        p.write_bytes(_OLE2_MAGIC)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdapterError) as exc_info:
                _convert_doc_to_docx(p, out_dir)
        msg = str(exc_info.value)
        assert "libreoffice" in msg.lower() or "LibreOffice" in msg
        assert "brew" in msg or "apt" in msg

    def test_rtf_raises_plain_language_error(self, tmp_path):
        from lib.docuseal_file_adapter import AdapterError, _convert_rtf_to_docx
        p = tmp_path / "doc.rtf"
        p.write_bytes(_RTF_MAGIC)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdapterError) as exc_info:
                _convert_rtf_to_docx(p, out_dir)
        assert "LibreOffice" in str(exc_info.value) or "libreoffice" in str(exc_info.value)

    def test_odt_raises_plain_language_error(self, tmp_path):
        from lib.docuseal_file_adapter import AdapterError, _convert_odt_to_docx
        p = tmp_path / "doc.odt"
        p.write_bytes(_odt_magic())
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdapterError) as exc_info:
                _convert_odt_to_docx(p, out_dir)
        assert "LibreOffice" in str(exc_info.value) or "libreoffice" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Round-trip: adapt() → detect_format on output
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_pdf_passthrough_round_trip(self, tmp_path):
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.pdf"
        src.write_bytes(_pdf_magic())
        out, endpoint = adapt(src)
        assert detect_format(out) == "pdf"
        assert endpoint == "pdf"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_docx_passthrough_round_trip(self, tmp_path):
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.docx"
        src.write_bytes(_docx_magic())
        out, endpoint = adapt(src)
        assert detect_format(out) == "docx"
        assert endpoint == "docx"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_html_passthrough_round_trip(self, tmp_path):
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.html"
        src.write_bytes(b"<!DOCTYPE html><html><body>hi</body></html>")
        out, endpoint = adapt(src)
        assert detect_format(out) == "html"
        assert endpoint == "html"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_md_to_html_round_trip(self, tmp_path):
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.md"
        src.write_text("# Hello\n\nParagraph.", encoding="utf-8")
        out, endpoint = adapt(src)
        assert detect_format(out) == "html"
        assert endpoint == "html"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_txt_to_pdf_round_trip(self, tmp_path):
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.txt"
        src.write_text("Hello world.\n\nSecond paragraph.", encoding="utf-8")
        out, endpoint = adapt(src)
        assert detect_format(out) == "pdf"
        assert endpoint == "pdf"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_png_to_pdf_round_trip(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.png"
        src.write_bytes(buf.getvalue())
        out, endpoint = adapt(src)
        assert detect_format(out) == "pdf"
        assert endpoint == "pdf"
        shutil.rmtree(out.parent, ignore_errors=True)

    def test_jpg_to_pdf_round_trip(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        import io
        img = Image.new("RGB", (1, 1))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        from lib.docuseal_file_adapter import adapt, detect_format
        src = tmp_path / "in.jpg"
        src.write_bytes(buf.getvalue())
        out, endpoint = adapt(src)
        assert detect_format(out) == "pdf"
        assert endpoint == "pdf"
        shutil.rmtree(out.parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# adapt_ctx context manager cleanup
# ---------------------------------------------------------------------------

class TestAdaptCtx:
    def test_tmp_dir_cleaned_up_after_exit(self, tmp_path):
        from lib.docuseal_file_adapter import adapt_ctx
        src = tmp_path / "in.pdf"
        src.write_bytes(_pdf_magic())
        with adapt_ctx(src) as (out, endpoint):
            tmp_dir = out.parent
            assert tmp_dir.exists()
            assert out.read_bytes()[:5] == b"%PDF-"
        assert not tmp_dir.exists()

    def test_endpoint_correct_in_ctx_manager(self, tmp_path):
        from lib.docuseal_file_adapter import adapt_ctx
        src = tmp_path / "in.pdf"
        src.write_bytes(_pdf_magic())
        with adapt_ctx(src) as (out, endpoint):
            assert endpoint == "pdf"
