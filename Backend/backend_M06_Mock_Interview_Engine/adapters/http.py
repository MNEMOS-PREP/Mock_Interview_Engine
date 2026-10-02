"""One small JSON client, standard library only.

The platform's modules call each other with `urllib` (M01's drill hand-off,
M02's calls to M01), so this does too rather than adding a dependency for a
dozen requests. Two things it does that a bare `urlopen` does not:

* **Every failure becomes `UpstreamUnavailable`** — connection refused, a
  timeout, a 5xx, a body that is not JSON. The caller has one thing to catch.
* **Selected status codes come back as values**, because some of them are
  answers: M05's 409 means "the bank cannot fill this round" and M13's 404
  means "not evaluated yet".
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ai_core.models import USER_AGENT

from .base import UpstreamUnavailable

#: Hot-path calls (M05 selection, M04 summary) must be quick; the outbox
#: drainer can afford to wait longer for M13.
DEFAULT_TIMEOUT_S = 3.0

#: What M04's `require_service` compares against (its keys.py), and what M15
#: sends. M13 reads a bare `SERVICE_SECRET` instead — accepted here as a
#: fallback so one keys.txt line serves both, and raised with M13 as an ask.
SERVICE_SECRET_VARS = ("M04_SERVICE_SECRET", "SERVICE_SECRET")


@dataclass
class Response:
    status: int
    body: Any


@dataclass
class JSONClient:
    module: str
    base_url: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    headers: dict[str, str] = field(default_factory=dict)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept: tuple[int, ...] = (),
        service: bool = False,
        timeout_s: float | None = None,
    ) -> Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            url = (
                f"{url}?{urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})}"
            )
        data = json.dumps(body, default=str).encode("utf-8") if body is not None else None
        sent = {"Accept": "application/json", "User-Agent": USER_AGENT, **self.headers}
        if data is not None:
            sent["Content-Type"] = "application/json"
        if service:
            secret = next(
                (v for v in (os.getenv(n, "").strip() for n in SERVICE_SECRET_VARS) if v), ""
            )
            if secret:
                sent["X-Service-Secret"] = secret
        sent.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=sent, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s or self.timeout_s) as resp:
                return Response(resp.status, _decode(self.module, resp.read()))
        except urllib.error.HTTPError as exc:
            payload = _decode(self.module, exc.read(), strict=False)
            if exc.code in accept:
                return Response(exc.code, payload)
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            raise UpstreamUnavailable(
                self.module, f"{method} {path} → {exc.code}: {detail}", status=exc.code
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpstreamUnavailable(self.module, f"{method} {path}: {exc}") from exc

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs) -> Response:
        return self.request("POST", path, body=body, **kwargs)


def _decode(module: str, raw: bytes, *, strict: bool = True) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if strict:
            raise UpstreamUnavailable(module, "response was not JSON") from exc
        return raw.decode("utf-8", errors="replace")


__all__ = ["DEFAULT_TIMEOUT_S", "JSONClient", "Response", "SERVICE_SECRET_VARS"]
