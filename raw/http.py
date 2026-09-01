"""Acesso HTTP conservador à BDTD."""

from __future__ import annotations

from collections.abc import Mapping
from email.utils import parsedate_to_datetime
import time

import requests

_USER_AGENT = "pipeline-bdtd/0.1"
_TIMEOUT = (10.0, 45.0)
_MAX_RETRIES = 3
_REQUEST_DELAY = 0.5
_BACKOFF_FACTOR = 1.0
_MAX_RETRY_AFTER = 60.0


class BdtdAccessError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BdtdClient:
    verification_cookie = "OasisbrVerify"
    verification_value = "verified_human"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, application/pdf;q=0.9, */*;q=0.1",
            }
        )
        self._last_request_at: float | None = None

    def get_json(self, url: str, *, params: Any = None) -> Mapping[str, Any]:
        response = self.request(url, params=params)
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise BdtdAccessError(f"a BDTD retornou JSON inválido para {url}") from exc
        if not isinstance(payload, Mapping):
            raise BdtdAccessError(f"a BDTD retornou JSON que não é um objeto para {url}")
        return payload

    def request(self, url: str, *, params: Any = None) -> requests.Response:
        verification_attempted = False
        for attempt in range(_MAX_RETRIES + 1):
            self._wait_before_request()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                if attempt >= _MAX_RETRIES:
                    raise BdtdAccessError(f"a requisição falhou para {url}: {exc}") from exc
                time.sleep(self._backoff(attempt))
                continue

            self._last_request_at = time.monotonic()
            if self._is_verification_response(response):
                if verification_attempted:
                    raise BdtdAccessError(f"a página de verificação persistiu para {url}")
                verification_attempted = True
                self._set_verification_cookie(url)
                continue

            if response.status_code in (429, 503):
                if attempt >= _MAX_RETRIES:
                    raise BdtdAccessError(f"a BDTD retornou HTTP {response.status_code} para {url}", status_code=response.status_code)
                time.sleep(self._retry_delay(response, attempt))
                continue

            if response.status_code >= 400:
                raise BdtdAccessError(f"a BDTD retornou HTTP {response.status_code} para {url}", status_code=response.status_code)
            return response

        raise AssertionError("request loop exhausted unexpectedly")

    def _wait_before_request(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _REQUEST_DELAY:
            time.sleep(_REQUEST_DELAY - elapsed)

    def _backoff(self, attempt: int) -> float:
        return _BACKOFF_FACTOR * (2**attempt)

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = _retry_after_seconds(response.headers)
        if retry_after is not None:
            return min(retry_after, _MAX_RETRY_AFTER)
        return self._backoff(attempt)

    def _set_verification_cookie(self, url: str) -> None:
        self.session.cookies.set(
            self.verification_cookie,
            self.verification_value,
            domain=requests.utils.urlparse(url).hostname,
            path="/",
        )

    @classmethod
    def _is_verification_response(cls, response: requests.Response) -> bool:
        content_type = response.headers.get("Content-Type", "").casefold()
        if "html" not in content_type:
            return False
        body = response.text[:20_000].casefold()
        return "oasisbrverify" in body or "browser verification" in body


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return max(0.0, retry_at.timestamp() - time.time())
