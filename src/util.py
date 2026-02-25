from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List

from dateutil import parser as date_parser


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime_to_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = date_parser.parse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.isoformat().replace("+00:00", "Z")


def compact_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def truncate_text(text: str, max_len: int) -> str:
    if max_len <= 3:
        return text[:max_len]
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def split_long_line(line: str, max_len: int) -> List[str]:
    if len(line) <= max_len:
        return [line]

    chunks: List[str] = []
    remaining = line
    while len(remaining) > max_len:
        split_at = remaining.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunk = remaining[:split_at].rstrip()
        if not chunk:
            chunk = remaining[:max_len]
            split_at = max_len
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def split_blocks_to_messages(blocks: Iterable[str], max_len: int = 2000) -> List[str]:
    messages: List[str] = []
    current = ""

    for block in blocks:
        clean_block = block.strip()
        if not clean_block:
            continue

        pieces = [clean_block]
        if len(clean_block) > max_len:
            pieces = []
            for line in clean_block.splitlines():
                line_chunks = split_long_line(line, max_len)
                pieces.extend(line_chunks)

        for piece in pieces:
            if not current:
                if len(piece) <= max_len:
                    current = piece
                else:
                    # Fallback hard split for extremely long tokens.
                    for i in range(0, len(piece), max_len):
                        messages.append(piece[i : i + max_len])
                    current = ""
                continue

            candidate = f"{current}\n\n{piece}"
            if len(candidate) <= max_len:
                current = candidate
            else:
                messages.append(current)
                if len(piece) <= max_len:
                    current = piece
                else:
                    for i in range(0, len(piece), max_len):
                        messages.append(piece[i : i + max_len])
                    current = ""

    if current:
        messages.append(current)

    return messages
