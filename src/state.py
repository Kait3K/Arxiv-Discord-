from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable

from .util import parse_datetime_to_utc, to_utc_iso

DEFAULT_STATE = {
    "sent_ids": [],
    "last_success_utc": None,
    "last_max_published_utc_by_topic": {},
}


def ensure_state_shape(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    state: Dict[str, Any] = dict(DEFAULT_STATE)
    if raw:
        state.update(raw)

    if not isinstance(state.get("sent_ids"), list):
        state["sent_ids"] = []
    if not isinstance(state.get("last_max_published_utc_by_topic"), dict):
        state["last_max_published_utc_by_topic"] = {}

    return state


def load_state(path: str) -> Dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        save_state(path, DEFAULT_STATE)
        return dict(DEFAULT_STATE)

    with state_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return ensure_state_shape(raw)


def save_state(path: str, state: Dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def get_last_success_utc(state: Dict[str, Any]) -> datetime | None:
    return parse_datetime_to_utc(state.get("last_success_utc"))


def compute_cutoff_utc(
    now_utc: datetime,
    last_success_utc: datetime | None,
    lookback_hours: int,
) -> datetime:
    lookback_delta = timedelta(hours=max(lookback_hours, 1))
    if last_success_utc is None:
        return now_utc - lookback_delta

    elapsed = now_utc - last_success_utc
    if elapsed < timedelta(0):
        elapsed = timedelta(0)

    safe_window = max(lookback_delta, elapsed)
    return now_utc - safe_window


def sent_id_set(state: Dict[str, Any]) -> set[str]:
    return set(state.get("sent_ids", []))


def append_sent_ids(state: Dict[str, Any], ids: Iterable[str], max_sent_ids: int) -> None:
    current = state.get("sent_ids", [])
    seen = set(current)

    for arxiv_id in ids:
        if arxiv_id and arxiv_id not in seen:
            current.append(arxiv_id)
            seen.add(arxiv_id)

    if len(current) > max_sent_ids:
        current = current[-max_sent_ids:]

    state["sent_ids"] = current


def update_success_metadata(
    state: Dict[str, Any],
    *,
    now_utc: datetime,
    last_max_published_utc_by_topic: Dict[str, datetime | None],
) -> None:
    state["last_success_utc"] = to_utc_iso(now_utc)

    topic_map = state.get("last_max_published_utc_by_topic", {})
    for topic_name, dt in last_max_published_utc_by_topic.items():
        if dt is not None:
            topic_map[topic_name] = to_utc_iso(dt)
    state["last_max_published_utc_by_topic"] = topic_map


def new_state() -> Dict[str, Any]:
    return ensure_state_shape(None)
