from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dateutil import tz

from .arxiv_client import ArxivClient, ArxivClientConfig
from .discord_webhook import DiscordWebhookClient
from .filter_rank import collect_candidates, split_recent_and_educational
from .parser import parse_feed
from .state import (
    append_sent_ids,
    compute_cutoff_utc,
    get_last_success_utc,
    load_state,
    save_state,
    sent_id_set,
    update_success_metadata,
)
from .util import to_utc_iso, truncate_text, utc_now

DEFAULT_CONFIG_PATH = "config.yaml"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def load_config(path: str) -> Dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml must contain a top-level mapping")
    return data


def quote_all_term(term: str) -> str:
    term = term.strip()
    if not term:
        return ""

    field_prefixes = ("all:", "ti:", "abs:", "cat:", "au:", "jr:", "rn:", "id:")
    lowered = term.lower()
    if lowered.startswith(field_prefixes):
        return term

    escaped = term.replace('"', '\\"')
    return f'all:"{escaped}"'


def build_search_query(topic: Dict[str, Any]) -> str:
    query_terms = topic.get("query_terms", [])
    categories = topic.get("categories", [])

    term_parts = [quote_all_term(str(term)) for term in query_terms if str(term).strip()]
    term_parts = [part for part in term_parts if part]
    cat_parts = [f"cat:{cat}" for cat in categories if str(cat).strip()]

    groups = []
    if term_parts:
        groups.append(f"({' OR '.join(term_parts)})")
    if cat_parts:
        groups.append(f"({' OR '.join(cat_parts)})")

    if not groups:
        raise ValueError(f"Topic '{topic.get('name', 'unknown')}' has no query_terms/categories")

    return " AND ".join(groups)


def format_author(entry: Dict[str, Any]) -> str:
    authors = entry.get("authors") or []
    if not authors:
        return "Unknown"
    first = authors[0]
    if len(authors) > 1:
        return f"{first} et al."
    return first


def format_entry_line(entry: Dict[str, Any], title_max_length: int) -> str:
    star = "✔︎ " if entry.get("educational") else ""
    title = truncate_text(entry.get("title", "(untitled)"), title_max_length)
    author = format_author(entry)
    category = entry.get("primary_category", "unknown")
    url = entry.get("abs_url", "")
    return f"- {star}{title} - {author} - {category} - {url}"


def build_digest_blocks(
    *,
    now_local: datetime,
    cutoff_utc: datetime,
    recent_window_days: int,
    header_template: str,
    topic_results: List[Dict[str, Any]],
    title_max_length: int,
) -> List[str]:
    date_jst = now_local.strftime("%Y-%m-%d")
    datetime_jst = now_local.strftime("%Y-%m-%d %H:%M %Z")
    header = header_template.format(date_jst=date_jst, datetime_jst=datetime_jst)

    count_summary = ", ".join(
        (
            f"{result['name']} (recent {len(result['recent_entries'])}, "
            f"educational {len(result['educational_entries'])})"
        )
        for result in topic_results
    )

    blocks = [
        "\n".join(
            [
                header,
                f"Time: {datetime_jst}",
                f"Cutoff (UTC): {to_utc_iso(cutoff_utc)}",
                f"Counts: {count_summary}",
            ]
        )
    ]

    for result in topic_results:
        name = result["name"]
        recent_entries = result["recent_entries"]
        educational_entries = result["educational_entries"]

        section_lines = [
            f"[{name}] recent {len(recent_entries)} / educational✔︎ {len(educational_entries)}",
            f"Recent (within {recent_window_days} days, submittedDate desc):",
        ]
        if not recent_entries:
            section_lines.append("- (no recent papers)")
        else:
            for entry in recent_entries:
                section_lines.append(format_entry_line(entry, title_max_length))

        section_lines.append("Educational / Beginner-friendly ✔︎:")
        if not educational_entries:
            section_lines.append("- (no educational papers)")
        else:
            for entry in educational_entries:
                section_lines.append(format_entry_line(entry, title_max_length))

        blocks.append("\n".join(section_lines))

    return blocks


def run() -> int:
    setup_logging()

    config = load_config(DEFAULT_CONFIG_PATH)
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("Environment variable DISCORD_WEBHOOK_URL is required")

    arxiv_conf = config.get("arxiv", {})
    state_conf = config.get("state", {})
    discord_conf = config.get("discord", {})

    inter_query_sleep = float(arxiv_conf.get("inter_query_sleep_seconds", 3.1))
    if inter_query_sleep < 3.0:
        logging.warning(
            "inter_query_sleep_seconds is %.2f (<3.0). Overriding to 3.1 to comply with arXiv policy.",
            inter_query_sleep,
        )
        inter_query_sleep = 3.1

    max_results_per_topic = int(arxiv_conf.get("max_results_per_topic", 200))
    legacy_max_items_per_topic = int(config.get("max_items_per_topic", 5))
    max_recent_items_per_topic = int(
        config.get(
            "max_recent_items_per_topic",
            config.get("max_latest_items_per_topic", legacy_max_items_per_topic),
        )
    )
    max_educational_items_per_topic = int(config.get("max_educational_items_per_topic", 1))
    lookback_hours = int(config.get("lookback_hours", 36))
    recent_window_days = int(config.get("recent_window_days", 7))
    if recent_window_days < 1:
        logging.warning("recent_window_days=%s is invalid. Overriding to 7.", recent_window_days)
        recent_window_days = 7
    report_timezone = str(config.get("report_timezone", "Asia/Tokyo"))
    title_max_length = int(discord_conf.get("title_max_length", 120))
    header_template = str(discord_conf.get("header_template", "arXiv Daily Digest ({date_jst})"))

    state_path = str(state_conf.get("path", "state/state.json"))
    max_sent_ids = int(state_conf.get("max_sent_ids", 20000))

    state = load_state(state_path)
    now_utc = utc_now()
    last_success_utc = get_last_success_utc(state)
    state_cutoff_utc = compute_cutoff_utc(now_utc, last_success_utc, lookback_hours)
    recent_cutoff_utc = now_utc - timedelta(days=recent_window_days)
    candidate_cutoff_utc = min(state_cutoff_utc, recent_cutoff_utc)

    logging.info("last_success_utc=%s", to_utc_iso(last_success_utc) if last_success_utc else "None")
    logging.info(
        "lookback_hours=%s state_cutoff_utc=%s recent_window_days=%s recent_cutoff_utc=%s candidate_cutoff_utc=%s",
        lookback_hours,
        to_utc_iso(state_cutoff_utc),
        recent_window_days,
        to_utc_iso(recent_cutoff_utc),
        to_utc_iso(candidate_cutoff_utc),
    )

    sent_ids = sent_id_set(state)
    topic_results: List[Dict[str, Any]] = []
    last_max_published_utc_by_topic: Dict[str, datetime | None] = {}

    arxiv_client = ArxivClient(
        ArxivClientConfig(
            endpoint=str(arxiv_conf.get("endpoint", "http://export.arxiv.org/api/query")),
            user_agent=str(
                arxiv_conf.get(
                    "user_agent",
                    "arxiv-discord-digest/1.0 (contact: your-email@example.com)",
                )
            ),
            request_timeout_seconds=int(arxiv_conf.get("request_timeout_seconds", 30)),
        )
    )
    discord_client = DiscordWebhookClient(
        webhook_url,
        timeout_seconds=int(discord_conf.get("request_timeout_seconds", 30)),
        max_content_length=int(discord_conf.get("max_content_length", 2000)),
    )

    topics = config.get("topics", [])
    if not topics:
        raise ValueError("No topics configured in config.yaml")

    try:
        for idx, topic in enumerate(topics):
            topic_name = str(topic.get("name", f"topic-{idx + 1}"))
            search_query = build_search_query(topic)
            logging.info("topic=%s query=%s", topic_name, search_query)

            xml_text = arxiv_client.fetch(
                search_query,
                start=0,
                max_results=max_results_per_topic,
                sort_by="submittedDate",
                sort_order="descending",
            )
            parsed_entries = parse_feed(xml_text)
            logging.info("topic=%s fetched_entries=%s", topic_name, len(parsed_entries))

            max_published = None
            for entry in parsed_entries:
                published = entry.get("published_utc")
                if published and (max_published is None or published > max_published):
                    max_published = published
            last_max_published_utc_by_topic[topic_name] = max_published

            candidates = collect_candidates(
                parsed_entries,
                cutoff_utc=candidate_cutoff_utc,
                sent_ids=sent_ids,
            )
            recent_entries, educational_entries = split_recent_and_educational(
                candidates,
                max_recent_items=max_recent_items_per_topic,
                max_educational_items=max_educational_items_per_topic,
            )
            logging.info(
                "topic=%s candidates=%s recent=%s educational=%s",
                topic_name,
                len(candidates),
                len(recent_entries),
                len(educational_entries),
            )

            topic_results.append(
                {
                    "name": topic_name,
                    "recent_entries": recent_entries,
                    "educational_entries": educational_entries,
                }
            )

            topic_sent_entries = recent_entries + educational_entries
            for entry in topic_sent_entries:
                # Avoid duplicates across topics within the same run.
                sent_ids.add(entry["arxiv_id"])

            if idx < len(topics) - 1:
                logging.info("sleep %.1f sec between arXiv queries", inter_query_sleep)
                time.sleep(inter_query_sleep)

        tz_info = tz.gettz(report_timezone)
        if tz_info is None:
            logging.warning("Invalid report timezone '%s'. Falling back to UTC.", report_timezone)
            now_local = now_utc
        else:
            now_local = now_utc.astimezone(tz_info)

        blocks = build_digest_blocks(
            now_local=now_local,
            cutoff_utc=candidate_cutoff_utc,
            recent_window_days=recent_window_days,
            header_template=header_template,
            topic_results=topic_results,
            title_max_length=title_max_length,
        )
        messages = discord_client.build_messages(blocks)

        total_selected = sum(
            len(result["recent_entries"]) + len(result["educational_entries"])
            for result in topic_results
        )
        logging.info(
            "digest totals: topics=%s selected_entries=%s messages=%s",
            len(topic_results),
            total_selected,
            len(messages),
        )

        sent_message_count = discord_client.send_messages(messages)
        logging.info("discord_sent_messages=%s", sent_message_count)

        sent_entry_ids = [
            entry["arxiv_id"]
            for result in topic_results
            for entry in (result.get("recent_entries", []) + result.get("educational_entries", []))
        ]
        append_sent_ids(state, sent_entry_ids, max_sent_ids=max_sent_ids)
        update_success_metadata(
            state,
            now_utc=now_utc,
            last_max_published_utc_by_topic=last_max_published_utc_by_topic,
        )
        save_state(state_path, state)

        logging.info(
            "state updated: sent_ids=%s last_success_utc=%s",
            len(state.get("sent_ids", [])),
            state.get("last_success_utc"),
        )
        return 0
    finally:
        arxiv_client.close()
        discord_client.close()


def main() -> None:
    try:
        exit_code = run()
    except Exception:
        logging.exception("Execution failed")
        raise SystemExit(1)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
