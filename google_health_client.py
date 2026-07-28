from __future__ import annotations

import json
import math
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests


class GoogleHealthError(RuntimeError):
    pass


class GoogleHealthClient:
    BASE_URL = "https://health.googleapis.com/v4"

    def __init__(
        self,
        token_file: str | Path = "private/google_health_token.json",
    ) -> None:
        self.token_file = Path(
            os.getenv("GOOGLE_HEALTH_TOKEN_FILE", str(token_file))
        )
        self.token = self._load_token()
        self.session = requests.Session()

    def _load_token(self) -> dict[str, Any]:
        env_refresh = os.getenv("GOOGLE_HEALTH_REFRESH_TOKEN")
        env_client_id = os.getenv("GOOGLE_HEALTH_CLIENT_ID")
        env_client_secret = os.getenv("GOOGLE_HEALTH_CLIENT_SECRET")

        if env_refresh and env_client_id and env_client_secret:
            return {
                "refresh_token": env_refresh,
                "client_id": env_client_id,
                "client_secret": env_client_secret,
                "token_uri": "https://oauth2.googleapis.com/token",
                "access_token": os.getenv("GOOGLE_HEALTH_ACCESS_TOKEN", ""),
                "expires_at": 0,
            }

        if not self.token_file.exists():
            raise FileNotFoundError(
                f"Token file not found: {self.token_file.resolve()}. "
                "Run google_health_auth.py first."
            )
        return json.loads(self.token_file.read_text(encoding="utf-8"))

    def _save_token(self) -> None:
        if os.getenv("GOOGLE_HEALTH_REFRESH_TOKEN"):
            return
        self.token_file.write_text(
            json.dumps(self.token, indent=2), encoding="utf-8"
        )

    def _refresh_access_token(self) -> str:
        response = requests.post(
            self.token.get(
                "token_uri", "https://oauth2.googleapis.com/token"
            ),
            timeout=30,
            data={
                "client_id": self.token["client_id"],
                "client_secret": self.token["client_secret"],
                "refresh_token": self.token["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if not response.ok:
            raise GoogleHealthError(
                f"Token refresh failed ({response.status_code}): "
                f"{response.text}"
            )

        refreshed = response.json()
        self.token["access_token"] = refreshed["access_token"]
        self.token["expires_in"] = refreshed.get("expires_in", 3599)
        self.token["expires_at"] = (
            int(time.time()) + int(self.token["expires_in"]) - 60
        )
        if refreshed.get("scope"):
            self.token["scope"] = refreshed["scope"]
        self._save_token()
        return self.token["access_token"]

    def _access_token(self) -> str:
        access_token = self.token.get("access_token", "")
        expires_at = int(self.token.get("expires_at", 0) or 0)
        if not access_token or time.time() >= expires_at:
            return self._refresh_access_token()
        return access_token

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        response = self.session.request(
            method=method,
            url=url,
            params=params,
            json=json_body,
            timeout=60,
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Accept": "application/json",
            },
        )
        if not response.ok:
            raise GoogleHealthError(
                f"Google Health API error ({response.status_code}) "
                f"for {method} {url}: {response.text}"
            )
        return response.json() if response.content else {}

    def get_identity(self) -> dict[str, Any]:
        return self.request("GET", "users/me/identity")

    @staticmethod
    def _civil_midnight(value: date) -> dict[str, Any]:
        return {
            "date": {
                "year": value.year,
                "month": value.month,
                "day": value.day,
            },
            "time": {},
        }

    def daily_rollup(
        self,
        data_type: str,
        start_date: date,
        end_date: date,
        *,
        window_size_days: int = 1,
        data_source_family: str | None = None,
    ) -> dict[str, Any]:
        """Roll up complete civil days; end_date is inclusive."""
        if window_size_days < 1:
            raise ValueError("window_size_days must be at least 1.")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date.")

        end_exclusive = end_date + timedelta(days=1)
        total_days = (end_exclusive - start_date).days

        # Google Health permits at most a 90-day range for steps,
        # nutrition-log, and most other daily-rollup data types. The API also
        # validates pageSize * windowSizeDays against that limit, so request
        # only the number of windows actually needed instead of the generic
        # maximum page size.
        if total_days > 90:
            raise ValueError(
                "daily_rollup supports at most 90 days for this data type. "
                "Split longer periods into multiple requests."
            )

        window_count = math.ceil(total_days / window_size_days)
        maximum_windows = max(1, 90 // window_size_days)
        page_size = min(window_count, maximum_windows, 10000)

        payload: dict[str, Any] = {
            "range": {
                "start": self._civil_midnight(start_date),
                "end": self._civil_midnight(end_exclusive),
            },
            "windowSizeDays": window_size_days,
            "pageSize": page_size,
        }
        if data_source_family:
            payload["dataSourceFamily"] = data_source_family

        return self.request(
            "POST",
            f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
            json_body=payload,
        )

    def list_data_points(
        self,
        data_type: str,
        *,
        filter_expression: str | None = None,
        page_size: int = 1000,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if filter_expression:
            params["filter"] = filter_expression
        if page_token:
            params["page_token"] = page_token

        return self.request(
            "GET",
            f"users/me/dataTypes/{data_type}/dataPoints",
            params=params,
        )

    def reconcile_data_points(
        self,
        data_type: str,
        *,
        filter_expression: str | None = None,
        data_source_family: str | None = None,
        page_size: int = 1000,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if filter_expression:
            params["filter"] = filter_expression
        if data_source_family:
            params["dataSourceFamily"] = data_source_family
        if page_token:
            params["page_token"] = page_token

        return self.request(
            "GET",
            f"users/me/dataTypes/{data_type}/dataPoints:reconcile",
            params=params,
        )
