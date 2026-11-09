"""Nifty 100 nightly screening engine for QuantTrading."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf


NIFTY100_CONSTITUENTS_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
HISTORY_PERIOD = "2y"
CHUNK_SIZE = 20
NIFTY100_SCORE_MAX_PE = 80.0
NIFTY100_MIN_SHARPE = 0.5
NIFTY100_MAX_DRAWDOWN_PCT = 40.0


def fetch_nifty100_constituents() -> list[dict[str, str]]:
    """Get the current symbol/name list from the official NSE archive CSV."""
    request = Request(NIFTY100_CONSTITUENTS_URL, headers={"User-Agent": "Mozilla/5.0 QuantTrading research scanner"})
    with urlopen(request, timeout=30) as response:
        table = pd.read_csv(BytesIO(response.read()))
    columns = {str(column).strip().lower(): column for column in table.columns}
    symbol_column = columns.get("symbol")
    name_column = columns.get("company name") or columns.get("companyname")
    if symbol_column is None:
        raise ValueError("The NSE Nifty 100 list did not contain a Symbol column.")

    constituents = []
    seen = set()
    for _, row in table.iterrows():
        symbol = str(row[symbol_column]).strip().upper()
        if not symbol or symbol == "NAN" or symbol in seen:
            continue
        seen.add(symbol)
        company = str(row[name_column]).strip() if name_column is not None else symbol
        if company == "nan":
            company = symbol
        yahoo_symbol = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        constituents.append({"symbol": yahoo_symbol, "company": company})
    if len(constituents) < 90:
        raise ValueError(f"NSE returned only {len(constituents)} Nifty 100 constituents; refusing to rank an incomplete list.")
    return constituents


def _ticker_frame(bundle: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Extract one ticker from yfinance's ticker/field multi-index response."""
    frame = bundle
    if isinstance(bundle.columns, pd.MultiIndex):
        found = False
        for level in range(bundle.columns.nlevels):
            values = {str(value) for value in bundle.columns.get_level_values(level)}
            if symbol in values:
                frame = bundle.xs(symbol, axis=1, level=level, drop_level=True)
                found = True
                break
        if not found:
            raise ValueError("Ticker was absent from the batch response.")
    if isinstance(frame.columns, pd.MultiIndex):
        fields = {"open", "high", "low", "close", "volume"}
        flattened = []
        for column in frame.columns:
            match = next((str(part).strip().lower() for part in column if str(part).strip().lower() in fields), None)
            flattened.append(match.title() if match else str(column[-1]))
        frame.columns = flattened
    else:
        frame.columns = [str(column).strip().title() for column in frame.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [field for field in required if field not in frame.columns]
    if missing:
        raise ValueError(f"Daily data is missing {', '.join(missing)}.")
    frame = frame[required].copy().sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    for field in required:
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame.dropna(subset=["Close"])


def fetch_price_history(constituents: list[dict[str, str]]) -> tuple[dict[str, pd.DataFrame], list[dict[str, str]]]:
    """Download adjusted daily OHLCV in moderate batches to limit API load."""
    histories: dict[str, pd.DataFrame] = {}
    errors: list[dict[str, str]] = []
    symbols = [item["symbol"] for item in constituents]
    for offset in range(0, len(symbols), CHUNK_SIZE):
        batch = symbols[offset:offset + CHUNK_SIZE]
        try:
            bundle = yf.download(
                tickers=batch,
                period=HISTORY_PERIOD,
                interval="1d",
                auto_adjust=True,
                group_by="ticker",
                multi_level_index=True,
                progress=False,
                threads=True,
                timeout=30,
            )
        except Exception as exc:
            for symbol in batch:
                errors.append({"Symbol": symbol, "Error": str(exc)[:160]})
            continue

        if bundle is None or bundle.empty:
            for symbol in batch:
                errors.append({"Symbol": symbol, "Error": "Yahoo Finance returned no daily data for this batch."})
            continue
        for symbol in batch:
            try:
                histories[symbol] = _ticker_frame(bundle, symbol)
            except Exception as exc:
                errors.append({"Symbol": symbol, "Error": str(exc)[:160]})
    return histories, errors


def scan_nifty100(nifty_close: pd.Series | None = None, extra_symbols: tuple[str, ...] = ()) -> dict:
    """Scan Nifty 100 plus user-added Yahoo symbols; keep additions visible if filtered."""
    # Imported only when the scan starts so main.py can also import this module.
    import main

    constituents = fetch_nifty100_constituents()
    official_symbols = {item["symbol"] for item in constituents}
    official_count = len(constituents)
    extra_constituents = []
    requested_symbols = set()
    for raw_symbol in extra_symbols:
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        if "." not in symbol:
            symbol = f"{symbol}.NS"
        requested_symbols.add(symbol)
        if symbol not in official_symbols and all(item["symbol"] != symbol for item in extra_constituents):
            extra_constituents.append({"symbol": symbol, "company": symbol.removesuffix(".NS").replace("-", " ")})
    constituents.extend(extra_constituents)
    if nifty_close is None:
        nifty_close = main.download_nifty_close()
    nifty_close = pd.to_numeric(nifty_close, errors="coerce").dropna()
    nifty_sma200 = nifty_close.rolling(200, min_periods=200).mean()
    if len(nifty_close) < 200 or pd.isna(nifty_sma200.iloc[-1]):
        raise ValueError("At least 200 daily Nifty 50 closes are needed for the market filter.")

    as_of = pd.Timestamp(nifty_close.index[-1])
    market_price = float(nifty_close.iloc[-1])
    market_sma = float(nifty_sma200.iloc[-1])
    regime = "Bull" if market_price > market_sma else "Defensive"
    payload = {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe": "Nifty 100",
        "constituents": official_count,
        "scanned_symbols": len(constituents),
        "market_regime": regime,
        "nifty_close": market_price,
        "nifty_sma200": market_sma,
        "eligible_count": 0,
        "results": [],
        "errors": [],
        "message": "",
    }

    histories, errors = fetch_price_history(constituents)
    names = {item["symbol"]: item["company"] for item in constituents}
    custom_symbols = requested_symbols
    records = []
    for symbol, history in histories.items():
        try:
            frame = main.add_indicators(history)
            if len(frame) < 200:
                raise ValueError("Fewer than 200 daily candles were returned.")
            last = frame.iloc[-1]
            required = ["Close", "Open", "SMA20", "SMA50", "SMA200", "RSI", "MACD", "MACD Signal", "ATR", "Volume", "Volume Avg", "ADX", "CMF", "BB Upper"]
            if any(pd.isna(last[field]) for field in required) or last["ATR"] <= 0 or last["Volume Avg"] <= 0:
                raise ValueError("Required technical indicators are unavailable.")

            price = float(last["Close"])
            rsi = float(last["RSI"])
            # Official-universe stocks must pass every gate. User-added tickers stay
            # visible even when filtered so the table explains why they did not qualify.
            filter_reasons = []
            if regime != "Bull":
                filter_reasons.append("Nifty 50 is below its 200-day SMA")
            if price <= float(last["SMA200"]):
                filter_reasons.append("Price is at/below its 200-day SMA")
            if not 40 <= rsi <= 70:
                filter_reasons.append("RSI is outside 40–70")
            eligible = not filter_reasons
            is_custom = symbol in custom_symbols
            if not eligible and not is_custom:
                continue

            atr = float(last["ATR"])
            volume_ratio = float(last["Volume"] / last["Volume Avg"])
            adx = float(last["ADX"])
            cmf = float(last["CMF"])
            bb = float(last["BB %B"]) if pd.notna(last["BB %B"]) else float("nan")
            bb_value = bb if pd.notna(bb) else None
            sharpe = float(last["Sharpe 1Y"]) if pd.notna(last["Sharpe 1Y"]) else None
            max_dd = float(last["Max DD 1Y %"]) if pd.notna(last["Max DD 1Y %"]) else None

            # A missing P/E is omitted just as it is in the existing score.
            pe = main.download_pe(symbol)
            factors = [
                ("Price vs SMA 20", 10, 1.0 if price > float(last["SMA20"]) else -1.0),
                ("SMA 20 vs SMA 50", 10, 1.0 if float(last["SMA20"]) > float(last["SMA50"]) else -1.0),
                ("SMA 50 vs SMA 200", 10, 1.0 if float(last["SMA50"]) > float(last["SMA200"]) else -1.0),
                ("MACD vs signal", 12, 1.0 if float(last["MACD"]) > float(last["MACD Signal"]) else -1.0),
            ]
            rsi_ceiling = 80 if adx > 25 else 75
            if 50 <= rsi <= 70:
                rsi_signal = 1.0
            elif 70 < rsi <= rsi_ceiling:
                rsi_signal = 0.6
            elif 45 <= rsi < 50:
                rsi_signal = -0.2
            elif 35 <= rsi < 45:
                rsi_signal = -0.6
            else:
                rsi_signal = -1.0
            factors.append(("RSI", 10, rsi_signal))
            factors.append(("High-volume candle", 8, (1.0 if price >= float(last["Open"]) else -1.0) if volume_ratio >= main.BUY_VOLUME_MULTIPLE else 0.0))
            adx_signal = (1.0 if price > float(last["SMA50"]) else -1.0) if adx >= 25 else ((0.5 if price > float(last["SMA50"]) else -0.5) if adx >= main.ADX_MINIMUM else 0.0)
            factors.append(("ADX trend strength", 8, adx_signal))
            cmf_signal = 1.0 if cmf > 0.05 else (0.5 if cmf > 0 else (-1.0 if cmf < -0.05 else (-0.5 if cmf < 0 else 0.0)))
            factors.append(("CMF money flow", 8, cmf_signal))
            if pd.notna(bb):
                bb_signal = -1.0 if bb > 1.10 else (0.5 if 0.7 <= bb <= 1.10 else (0.0 if 0.3 <= bb < 0.7 else (-0.5 if bb <= 0.1 else -0.2)))
                factors.append(("Bollinger position", 8, bb_signal))
            if sharpe is not None:
                factors.append(("1Y Sharpe", 6, 1.0 if sharpe >= NIFTY100_MIN_SHARPE + 0.5 else (0.5 if sharpe >= NIFTY100_MIN_SHARPE else -1.0)))
            if max_dd is not None:
                dd_floor = -NIFTY100_MAX_DRAWDOWN_PCT
                factors.append(("1Y maximum drawdown", 6, 1.0 if max_dd >= dd_floor + 15 else (0.5 if max_dd >= dd_floor else -1.0)))
            if NIFTY100_SCORE_MAX_PE > 0 and pe is not None:
                factors.append(("Trailing P/E filter", 4, -1.0 if pe <= 0 else (0.5 if pe <= NIFTY100_SCORE_MAX_PE else -0.5)))

            score, rating, reason = main.weighted_score(factors)
            action = "BUY" if eligible and score >= 20 and 40 < rsi < 70 else ("WATCH" if eligible else "NOT ELIGIBLE")
            target_multiple, scale_multiple = main.market_risk_parameters(regime)
            records.append({
                "Company": names.get(symbol, symbol),
                "Symbol": symbol,
                "Universe": "Added" if is_custom else "Nifty 100",
                "Filter status": "Pass" if eligible else "Filtered: " + "; ".join(filter_reasons),
                "Date": as_of.strftime("%d %b %Y"),
                "Action": action,
                "Rating": rating,
                "Score": int(score),
                "Scenario": "Long",
                "Reason": ("Passes Nifty 50 alignment, price above SMA 200, and RSI 40–70. " if eligible else "Does not pass: " + "; ".join(filter_reasons) + ". ") + reason,
                "Market regime": regime,
                "Target ATR multiple": float(target_multiple),
                "Scale-out ATR multiple": float(scale_multiple),
                "Price": price,
                "Stop loss": price - main.ATR_STOP_MULTIPLE * atr,
                "Scale-out level": price + scale_multiple * atr,
                "Target": price + target_multiple * atr,
                "Entry plan": "Next market open · TBD",
                "Risk %": main.ATR_STOP_MULTIPLE * atr / price * 100,
                "Reward %": target_multiple * atr / price * 100,
                "Reward/Risk": target_multiple / main.ATR_STOP_MULTIPLE,
                "RSI (14)": rsi,
                "Trend": "Above SMA 200" if price > float(last["SMA200"]) else "At/below SMA 200",
                "Volume vs avg": volume_ratio,
                "SMA20": float(last["SMA20"]),
                "SMA50": float(last["SMA50"]),
                "SMA200": float(last["SMA200"]),
                "MACD": float(last["MACD"]),
                "MACD Signal": float(last["MACD Signal"]),
                "ATR (14)": atr,
                "ADX (14)": adx,
                "CMF (20)": cmf,
                "BB %B": bb_value,
                "P/E": pe,
                "Sharpe 1Y": sharpe,
                "Max DD 1Y %": max_dd,
                "Paper status": "User-added symbol · leaderboard research only" if is_custom else "Leaderboard research only · no order placed",
                "Paper entry": None,
                "Paper regime": regime,
                "Sessions held": None,
            })
        except Exception as exc:
            errors.append({"Symbol": symbol, "Error": str(exc)[:160]})

    records.sort(key=lambda row: (row["Universe"] != "Added", row["Filter status"] == "Pass", row["Score"], row["MACD"] > row["MACD Signal"], row["ADX (14)"]), reverse=True)
    payload["eligible_count"] = sum(row["Filter status"] == "Pass" for row in records)
    payload["results"] = records
    payload["errors"] = errors
    if not records:
        payload["message"] = "No Nifty 100 stocks passed the Nifty regime, RSI, and SMA 200 filters today."
    return payload
