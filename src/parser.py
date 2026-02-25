from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import feedparser

from .util import compact_whitespace, parse_datetime_to_utc

ARXIV_ID_PATTERN = re.compile(r"(?:https?://)?arxiv\.org/abs/(.+)$", re.IGNORECASE)
VERSION_PATTERN = re.compile(r"v\d+$", re.IGNORECASE)


NormalizedEntry = Dict[str, Any]


def extract_arxiv_id(raw_id: str) -> str:
    raw_id = (raw_id or "").strip()
    match = ARXIV_ID_PATTERN.search(raw_id)
    if match:
        return match.group(1)

    parsed = urlparse(raw_id)
    if parsed.netloc.lower().endswith("arxiv.org") and parsed.path.startswith("/abs/"):
        return parsed.path[len("/abs/") :].lstrip("/")

    return raw_id


def parse_feed(xml_text: str) -> List[NormalizedEntry]:
    parsed = feedparser.parse(xml_text)
    entries: List[NormalizedEntry] = []

    for entry in parsed.entries:
        arxiv_id = extract_arxiv_id(entry.get("id", ""))
        if not arxiv_id:
            continue

        if not VERSION_PATTERN.search(arxiv_id):
            # arXiv API usually includes the version in id, but keep a safe fallback.
            arxiv_id = f"{arxiv_id}v1"

        authors = []
        for author in entry.get("authors", []):
            if isinstance(author, dict):
                raw_name = author.get("name", "")
            else:
                raw_name = getattr(author, "name", "")
            name = compact_whitespace(raw_name)
            if name:
                authors.append(name)

        primary_category = None
        primary = entry.get("arxiv_primary_category")
        if isinstance(primary, dict):
            primary_category = primary.get("term")
        if not primary_category and entry.get("tags"):
            first_tag = entry["tags"][0]
            if isinstance(first_tag, dict):
                primary_category = first_tag.get("term")
            else:
                primary_category = getattr(first_tag, "term", None)

        normalized: NormalizedEntry = {
            "arxiv_id": arxiv_id,
            "title": compact_whitespace(entry.get("title", "")),
            "summary": compact_whitespace(entry.get("summary", "")),
            "authors": authors,
            "primary_category": primary_category or "unknown",
            "published_utc": parse_datetime_to_utc(entry.get("published")),
            "updated_utc": parse_datetime_to_utc(entry.get("updated")),
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        }
        entries.append(normalized)

    return entries
