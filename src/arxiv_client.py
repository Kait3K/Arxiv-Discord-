from __future__ import annotations

import logging
from dataclasses import dataclass

import requests


@dataclass
class ArxivClientConfig:
    endpoint: str
    user_agent: str
    request_timeout_seconds: int = 30


class ArxivClient:
    def __init__(self, config: ArxivClientConfig) -> None:
        self._config = config
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": config.user_agent})

    def fetch(
        self,
        search_query: str,
        *,
        start: int,
        max_results: int,
        sort_by: str = "submittedDate",
        sort_order: str = "descending",
    ) -> str:
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        logging.info(
            "arXiv request: endpoint=%s start=%s max_results=%s sortBy=%s sortOrder=%s",
            self._config.endpoint,
            start,
            max_results,
            sort_by,
            sort_order,
        )

        response = self._session.get(
            self._config.endpoint,
            params=params,
            timeout=self._config.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.text

    def close(self) -> None:
        self._session.close()
