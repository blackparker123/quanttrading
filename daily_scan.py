"""Run the Nifty 100 leaderboard once and write a JSON snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import main
from nifty100_engine import scan_nifty100


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Scan Nifty 100 after market close.")
    parser.add_argument("--output", default="daily_scan.json", help="Where to write the JSON scan result.")
    args = parser.parse_args()

    payload = scan_nifty100(main.download_nifty_close())
    output_path = Path(args.output)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    print(
        f"Nifty 100 scan {payload['as_of']}: {payload['eligible_count']} eligible stocks; "
        f"wrote {output_path}."
    )
    for error in payload.get("errors", []):
        print(f"Data issue for {error['Symbol']}: {error['Error']}")


if __name__ == "__main__":
    main_cli()
