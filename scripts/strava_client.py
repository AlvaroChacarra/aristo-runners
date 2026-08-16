from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class StravaError(RuntimeError):
    pass


class TemporaryStravaError(StravaError):
    pass


@dataclass(frozen=True)
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_at: int | None = None


class Transport(Protocol):
    def request(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: int
    ) -> tuple[int, Any, dict[str, str]]: ...


class UrllibTransport:
    def request(
        self, method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: int
    ) -> tuple[int, Any, dict[str, str]]:
        request = Request(url, method=method, headers=headers, data=data)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read()
            status = exc.code
            response_headers = dict(exc.headers.items()) if exc.headers else {}
        except URLError as exc:
            raise TemporaryStravaError("Network error while contacting Strava") from exc
        try:
            payload = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StravaError("Strava returned invalid JSON") from exc
        return status, payload, response_headers


class StravaClient:
    API_BASE = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"
    TEMPORARY_STATUS = (429, 500, 502, 503, 504)

    def __init__(self, access_token: str | None = None, transport: Transport | None = None, sleep=time.sleep):
        self.transport = transport or UrllibTransport()
        self.access_token = access_token
        self.sleep = sleep

    def _request(
        self,
        method: str,
        url: str,
        operation: str,
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> Any:
        encoded = urlencode(form).encode() if form else None
        request_headers = dict(headers or {})
        if form:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        for attempt in range(5):
            status, payload, response_headers = self.transport.request(method, url, request_headers, encoded, 30)
            if status in self.TEMPORARY_STATUS:
                if attempt == 4:
                    raise TemporaryStravaError(f"Temporary Strava error during {operation}: HTTP {status}")
                retry_after = response_headers.get("Retry-After")
                delay = min(float(retry_after), 30) if retry_after and retry_after.isdigit() else 2**attempt
                self.sleep(delay)
                continue
            if not 200 <= status < 300:
                raise StravaError(f"Strava rejected {operation}: HTTP {status}")
            return payload
        raise AssertionError("retry loop exhausted")

    def refresh(self, client_id: str, client_secret: str, refresh_token: str) -> TokenBundle:
        payload = self._request(
            "POST",
            self.TOKEN_URL,
            "token refresh",
            form={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
            raise StravaError("Token response is missing required fields")
        return TokenBundle(payload["access_token"], payload["refresh_token"], payload.get("expires_at"))

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.access_token:
            raise StravaError("No access token available")
        query = f"?{urlencode(params)}" if params else ""
        return self._request(
            "GET",
            f"{self.API_BASE}{path}{query}",
            path,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def discover_club(self, exact_name: str) -> int:
        clubs = self.get("/athlete/clubs")
        if not isinstance(clubs, list):
            raise StravaError("Athlete clubs response is not a list")
        matches = [club for club in clubs if club.get("name") == exact_name]
        if len(matches) != 1 or not matches[0].get("id"):
            raise StravaError(f"Expected exactly one club named {exact_name!r}; found {len(matches)}")
        return int(matches[0]["id"])

    def list_club_activities(self, club_id: int, per_page: int = 100, max_pages: int = 100) -> list[dict[str, Any]]:
        activities: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            batch = self.get(f"/clubs/{club_id}/activities", {"page": page, "per_page": per_page})
            if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                raise StravaError("Club activities response is not an array of objects")
            activities.extend(batch)
            if len(batch) < per_page:
                return activities
        raise StravaError(f"Pagination exceeded safety limit ({max_pages} pages)")
