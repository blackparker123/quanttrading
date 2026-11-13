"""Refresh private portfolio action prompts after the cash-market close."""

from __future__ import annotations

from datetime import datetime
import os
from zoneinfo import ZoneInfo

import main
from portfolio_storage import load_all_user_portfolios, save_portfolio_file


def main_cli() -> None:
    token = os.environ.get("PORTFOLIO_GITHUB_TOKEN", "").strip()
    gist_id = os.environ.get("PORTFOLIO_GIST_ID", "").strip()
    if not token or not gist_id:
        raise SystemExit("Set PORTFOLIO_GITHUB_TOKEN and PORTFOLIO_GIST_ID to enable private portfolio tracking.")

    portfolios = load_all_user_portfolios(token, gist_id)
    checked_positions = 0
    checked_users = 0
    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
    for filename, portfolio in portfolios:
        actions = []
        for position in portfolio.get("positions", []):
            ticker = str(position.get("Ticker", "")).strip()
            entry_price = position.get("Entry Price")
            entry_date = position.get("Entry Date")
            if not ticker or entry_price is None or not entry_date:
                continue
            try:
                result = main.evaluate_active_holding(ticker, float(entry_price), entry_date)
                result["Entry Date"] = result["Entry Date"].isoformat()
                result["As of"] = result["As of"].isoformat()
            except Exception as exc:
                result = {
                    "Ticker": ticker.upper(),
                    "Status": "NEEDS DATA",
                    "Tomorrow's Action": f"⚪ NEEDS DATA — {str(exc)[:150]}",
                }
            actions.append(result)
        portfolio["latest_actions"] = actions
        portfolio["last_checked"] = timestamp
        save_portfolio_file(token, gist_id, filename, portfolio)
        checked_users += 1
        checked_positions += len(actions)

    print(f"Private portfolio check complete: {checked_positions} position(s) across {checked_users} account(s).")


if __name__ == "__main__":
    main_cli()
