"""Refresh the local portfolio action prompts from the latest daily candles."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import main
from portfolio_storage import load_portfolio, save_portfolio


def main_cli() -> None:
    portfolio = load_portfolio()
    actions = []
    timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
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
    save_portfolio(portfolio)
    print(f"Local portfolio check complete: {len(actions)} position(s).")


if __name__ == "__main__":
    main_cli()
