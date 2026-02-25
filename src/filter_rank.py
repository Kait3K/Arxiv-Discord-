from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple


EDUCATIONAL_PATTERNS = [
    r"\bsurveys?\b",
    r"\btutorials?\b",
    r"\breviews?\b",
    r"\bprimer\b",
    r"\bintroduction\b",
    r"\bintroductory\b",
    r"\blecture\s*notes?\b",
    r"\bnotes?\b",
    r"\bpedagogical\b",
    r"\boverviews?\b",
    r"\ba\s+guide\b",
    r"\bbeginners?\b",
    r"\bfor\s+beginners?\b",
    r"\bfundamentals?\b",
    r"\bfoundations?\b",
    r"\bfrom\s+scratch\b",
    r"\bstep\s*by\s*step\b",
    r"\bhow\s+to\b",
    r"\bexplainer\b",
    r"\broadmap\b",
]
EDUCATIONAL_REGEX = re.compile("|".join(EDUCATIONAL_PATTERNS), flags=re.IGNORECASE)

Entry = Dict[str, Any]


def is_educational(title: str, summary: str) -> bool:
    target = f"{title}\n{summary}".lower()
    target = re.sub(r"[-_/]", " ", target)
    target = re.sub(r"\s+", " ", target).strip()
    return bool(EDUCATIONAL_REGEX.search(target))


def collect_candidates(
    entries: Iterable[Entry],
    *,
    cutoff_utc: datetime,
    sent_ids: set[str],
) -> List[Entry]:
    candidates: List[Entry] = []

    for entry in entries:
        arxiv_id = entry.get("arxiv_id")
        published_utc = entry.get("published_utc")

        if not arxiv_id or not published_utc:
            continue
        if published_utc < cutoff_utc:
            continue
        if arxiv_id in sent_ids:
            continue

        entry = dict(entry)
        entry["educational"] = is_educational(entry.get("title", ""), entry.get("summary", ""))
        candidates.append(entry)

    def sort_key(item: Entry) -> float:
        published = item.get("published_utc")
        published_ts = published.timestamp() if published else 0.0
        return -published_ts

    return sorted(candidates, key=sort_key)


def split_recent_and_educational(
    candidates: Iterable[Entry],
    *,
    max_recent_items: int,
    max_educational_items: int,
) -> Tuple[List[Entry], List[Entry]]:
    non_educational: List[Entry] = []
    educational_pool: List[Entry] = []

    for entry in candidates:
        if entry.get("educational"):
            educational_pool.append(entry)
        else:
            non_educational.append(entry)

    recent_entries = non_educational[: max(max_recent_items, 0)]

    educational_limit = max(max_educational_items, 0)
    if educational_limit == 0 or not educational_pool:
        return recent_entries, []

    if len(educational_pool) <= educational_limit:
        return recent_entries, educational_pool

    return recent_entries, random.sample(educational_pool, k=educational_limit)
