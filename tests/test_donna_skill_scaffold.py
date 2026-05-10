"""
Scaffold tests for the /donna skill.

Verifies:
  (a) SKILL.md has required frontmatter fields
  (b) All 4 handlers are importable
  (c) Each handler raises NotImplementedError with a helpful message pointing to W2b
  (d) export raises ValueError on bad format before reaching NotImplementedError
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path so skills/ is importable
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

SKILL_MD = REPO_ROOT / "skills" / "donna" / "SKILL.md"
REQUIRED_FRONTMATTER = {"name", "version", "commands", "mcp_surface"}


# --- (a) SKILL.md parses with frontmatter ---

def test_skill_md_exists():
    assert SKILL_MD.exists(), f"SKILL.md not found at {SKILL_MD}"


def test_skill_md_has_frontmatter():
    text = SKILL_MD.read_text()
    assert text.startswith("---"), "SKILL.md must start with YAML frontmatter (---)"
    end = text.index("---", 3)
    frontmatter_block = text[3:end]
    for field in REQUIRED_FRONTMATTER:
        assert field in frontmatter_block, (
            f"SKILL.md frontmatter missing required field: '{field}'"
        )


def test_skill_md_has_four_commands():
    text = SKILL_MD.read_text()
    for cmd in ("analyse", "draft", "review", "export"):
        assert f"/donna {cmd}" in text, f"SKILL.md missing /donna {cmd} command"


# --- (b) All 4 handlers importable ---

def test_analyse_importable():
    from skills.donna.handlers.analyse import analyse  # noqa: F401


def test_draft_importable():
    from skills.donna.handlers.draft import draft  # noqa: F401


def test_review_importable():
    from skills.donna.handlers.review import review  # noqa: F401


def test_export_importable():
    from skills.donna.handlers.export import export  # noqa: F401


# --- (c) NotImplementedError raised with W2b message ---

def test_analyse_raises_not_implemented():
    from skills.donna.handlers.analyse import analyse
    with pytest.raises(NotImplementedError) as exc:
        analyse("some contract text")
    assert "W2b" in str(exc.value), "Error message must reference W2b wiring"
    assert "donna-mcp" in str(exc.value), "Error message must reference donna-mcp"


def test_draft_raises_not_implemented():
    from skills.donna.handlers.draft import draft
    with pytest.raises(NotImplementedError) as exc:
        draft("nda")
    assert "W2b" in str(exc.value)
    assert "donna-mcp" in str(exc.value)


def test_review_raises_not_implemented():
    from skills.donna.handlers.review import review
    with pytest.raises(NotImplementedError) as exc:
        review("some contract text")
    assert "W2b" in str(exc.value)
    assert "donna-mcp" in str(exc.value)


def test_export_raises_not_implemented_on_valid_format():
    from skills.donna.handlers.export import export
    with pytest.raises(NotImplementedError) as exc:
        export({"summary": "test"}, "pdf")
    assert "W2b" in str(exc.value)
    assert "donna-mcp" in str(exc.value)


# --- (d) export raises ValueError on bad format before NotImplementedError ---

def test_export_raises_value_error_on_bad_format():
    from skills.donna.handlers.export import export
    with pytest.raises(ValueError, match="Unsupported format"):
        export({"summary": "test"}, "xlsx")


def test_export_supported_formats_constant():
    from skills.donna.handlers.export import SUPPORTED_FORMATS
    assert set(SUPPORTED_FORMATS) == {"pdf", "docx", "md"}
