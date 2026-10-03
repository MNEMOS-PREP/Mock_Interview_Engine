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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ai_core import service as platform_service
from ai_core.models import USER_AGENT

from .base import UpstreamUnavailable

#: Hot-path calls (M05 selection, M04 summary) must be quick; the outbox
#: drainer can afford to wait longer for M13.
DEFAULT_TIMEOUT_S = 3.0

#: Kept for importers. The secret is Platform_Core's since v0.12.0
#: (`ai_core.service`): this file, M13's `emit.py` and M15's theta fetch had
#: each read it their own way, under two names.
SERVICE_SECRET_VARS = platform_service.SECRET_VARS


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
            # Never empty: with nothing configured, the machine secret every
            # module on this host shares.
            sent.update(platform_service.headers())
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
