"""Stable ids for claims, so the same fact keeps its verification record across checks."""

from __future__ import annotations

import hashlib
import re


def normalise_claim(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d)", "", text.casefold())
    text = re.sub(r"[^\w\s$%.€£₹]", " ", text)
    return " ".join(text.split()).rstrip(".")


def passport_id(text: str) -> str:
    """The same claim, ignoring case, spacing and punctuation, gets the same id."""
    digest = hashlib.sha1(normalise_claim(text).encode()).hexdigest()
    return f"CLM-{digest[:6].upper()}"
