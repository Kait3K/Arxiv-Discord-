from __future__ import annotations

import logging
from typing import Iterable, List

import requests

from .util import split_blocks_to_messages


class DiscordWebhookError(RuntimeError):
    pass


class DiscordWebhookClient:
    def __init__(self, webhook_url: str, *, timeout_seconds: int = 30, max_content_length: int = 2000) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds
        self.max_content_length = max_content_length
        self._session = requests.Session()

    def build_messages(self, blocks: Iterable[str]) -> List[str]:
        return split_blocks_to_messages(blocks, max_len=self.max_content_length)

    def send_messages(self, messages: Iterable[str]) -> int:
        sent_count = 0
        for index, content in enumerate(messages, start=1):
            self.send(content)
            sent_count += 1
            logging.info("Discord message sent (%s)", index)
        return sent_count

    def send(self, content: str) -> None:
        if not content:
            return
        if len(content) > self.max_content_length:
            raise DiscordWebhookError(f"Content is too long: {len(content)} > {self.max_content_length}")

        payload = {
            "content": content,
            "allowed_mentions": {"parse": []},
        }
        response = self._session.post(self.webhook_url, json=payload, timeout=self.timeout_seconds)
        if response.status_code not in (200, 204):
            raise DiscordWebhookError(
                f"Discord webhook failed with status={response.status_code}, body={response.text[:500]}"
            )

    def close(self) -> None:
        self._session.close()
