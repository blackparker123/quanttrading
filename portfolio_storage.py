"""Local-only persistence for the Active Portfolio ledger."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
PORTFOLIO_PATH = PROJECT_DIR / "data" / "active_portfolio.json"
EMPTY_PORTFOLIO = {"positions": [], "latest_actions": [], "last_checked": None}


def load_portfolio() -> dict:
    """Load this computer's portfolio file; no file means an empty ledger."""
    if not PORTFOLIO_PATH.exists():
        return dict(EMPTY_PORTFOLIO)
    try:
        payload = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError("The local portfolio file is damaged or not valid JSON. It was left untouched.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("positions", []), list):
        raise ValueError("The local portfolio file has an invalid positions list. It was left untouched.")
    payload.setdefault("positions", [])
    payload.setdefault("latest_actions", [])
    payload.setdefault("last_checked", None)
    return payload


def save_portfolio(payload: dict) -> None:
    """Atomically save the ledger and latest prompts on this computer only."""
    if not isinstance(payload, dict) or not isinstance(payload.get("positions"), list):
        raise ValueError("Cannot save an invalid portfolio document.")
    PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    temporary_path = PORTFOLIO_PATH.with_suffix(".tmp")
    temporary_path.write_text(encoded, encoding="utf-8")
    temporary_path.replace(PORTFOLIO_PATH)

