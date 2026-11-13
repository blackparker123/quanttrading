"""Per-user, private GitHub Gist storage for QuantTrading holdings."""

from __future__ import annotations

import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


FILE_PREFIX = "quanttrading_portfolio_user_"
FILE_SUFFIX = ".json"
EMPTY_PORTFOLIO = {"positions": [], "latest_actions": [], "last_checked": None}


def user_file_name(oidc_subject: str) -> str:
    """Make a stable storage key without putting names or emails in the gist."""
    digest = hashlib.sha256(oidc_subject.encode("utf-8")).hexdigest()
    return f"{FILE_PREFIX}{digest}{FILE_SUFFIX}"


def _request(method: str, token: str, gist_id: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"https://api.github.com/gists/{gist_id}",
        data=body,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "QuantTrading-private-portfolio",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise ValueError(f"Private portfolio storage returned HTTP {exc.code}. Check its token and gist ID.") from None
        raise ValueError(f"Private portfolio storage returned HTTP {exc.code}.") from None
    except URLError as exc:
        raise ValueError(f"Could not reach private portfolio storage: {exc.reason}.") from None


def _read_gist(token: str, gist_id: str) -> dict:
    gist = _request("GET", token, gist_id)
    if gist.get("public") is True:
        raise ValueError("Portfolio storage must be a private GitHub Gist.")
    return gist


def load_user_portfolio(token: str, gist_id: str, oidc_subject: str) -> dict:
    """Load only the file belonging to the authenticated OIDC subject."""
    gist = _read_gist(token, gist_id)
    file_data = (gist.get("files") or {}).get(user_file_name(oidc_subject))
    if file_data is None:
        return dict(EMPTY_PORTFOLIO)
    if file_data.get("truncated"):
        raise ValueError("Your private portfolio file is too large to read safely.")
    try:
        payload = json.loads(file_data.get("content", ""))
    except json.JSONDecodeError:
        raise ValueError("Your private portfolio file is not valid JSON.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("positions", []), list):
        raise ValueError("Your private portfolio file has an invalid positions list.")
    payload.setdefault("positions", [])
    payload.setdefault("latest_actions", [])
    payload.setdefault("last_checked", None)
    return payload


def save_user_portfolio(token: str, gist_id: str, oidc_subject: str, payload: dict) -> None:
    """Update only the authenticated user's private portfolio file."""
    gist = _read_gist(token, gist_id)
    filename = user_file_name(oidc_subject)
    current = dict(EMPTY_PORTFOLIO)
    file_data = (gist.get("files") or {}).get(filename)
    if file_data and not file_data.get("truncated"):
        try:
            current.update(json.loads(file_data.get("content", "")))
        except (json.JSONDecodeError, TypeError):
            pass
    updated = {**current, **payload}
    # The scheduled job may have refreshed these fields since this browser session loaded.
    updated["latest_actions"] = current.get("latest_actions", [])
    updated["last_checked"] = current.get("last_checked")
    content = json.dumps(updated, ensure_ascii=False, allow_nan=False, indent=2)
    _request(
        "PATCH",
        token,
        gist_id,
        {"files": {filename: {"content": content}}},
    )


def load_all_user_portfolios(token: str, gist_id: str) -> list[tuple[str, dict]]:
    """Read namespaced files for the scheduled job; callers must not log IDs."""
    gist = _read_gist(token, gist_id)
    portfolios = []
    for filename, file_data in (gist.get("files") or {}).items():
        if not filename.startswith(FILE_PREFIX) or not filename.endswith(FILE_SUFFIX):
            continue
        if file_data.get("truncated"):
            continue
        try:
            payload = json.loads(file_data.get("content", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("positions", []), list):
            payload.setdefault("positions", [])
            payload.setdefault("latest_actions", [])
            payload.setdefault("last_checked", None)
            portfolios.append((filename, payload))
    return portfolios


def save_portfolio_file(token: str, gist_id: str, filename: str, payload: dict) -> None:
    """Update an existing user file from the private scheduled workflow."""
    if not filename.startswith(FILE_PREFIX) or not filename.endswith(FILE_SUFFIX):
        raise ValueError("Invalid private portfolio filename.")
    _read_gist(token, gist_id)
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    _request("PATCH", token, gist_id, {"files": {filename: {"content": content}}})

