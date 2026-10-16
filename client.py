"""One real HTTP adapter and a visibly separate fixture adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request: Request, timeout: int):
    # Never forward the authorization header through an upstream redirect.
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def load_fixture(scenario: str) -> dict:
    if scenario not in {"confident", "uncertain"}:
        raise ValueError("Unknown fixture scenario.")
    path = Path(__file__).parent / "fixtures" / f"{scenario}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_live(payload: dict) -> dict:
    """Send all questions together; keys never appear in reports or error text."""
    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Set TYPESAFE_API_KEY before using live mode.")
    if any(ord(char) < 33 or ord(char) > 126 for char in api_key):
        raise ValueError("TYPESAFE_API_KEY contains invalid characters.")
    body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("Request exceeds 32 MiB; use fewer or smaller images.")
    request = Request(
        ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "TypeSafe-Danger-Zone-Images": "true",
        },
        method="POST",
    )
    try:
        with _open(request, timeout=60) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Do not echo an arbitrary server/proxy response that could contain credentials.
        raise RuntimeError(f"TypeSafe request failed with HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("TypeSafe connection failed or timed out.") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("TypeSafe response exceeds 4 MiB.")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RuntimeError("TypeSafe returned invalid JSON.") from None
    return result
