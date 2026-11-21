"""Prompt files and helpers for placing untrusted text inside prompts."""

from __future__ import annotations

import re
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def neutralise_tag(text: str, tag: str) -> str:
    """Stop untrusted text from opening or closing our delimiter tag."""
    pattern = rf"<\s*/?\s*{re.escape(tag)}\b[^>\n]*>?"
    return re.sub(pattern, "[removed tag]", text, flags=re.IGNORECASE)
