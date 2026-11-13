"""QuantTrading: a data-driven, research-only Nifty 50 swing scanner."""

from __future__ import annotations

from datetime import datetime
import inspect
import json
import math
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots
from nifty100_engine import scan_nifty100


# Edit this list to scan other Yahoo Finance symbols. NSE symbols end in .NS.
WATCHLIST = {
    "HDFCBANK.NS": "HDFC Bank",
    "ICICIBANK.NS": "ICICI Bank",
    "RELIANCE.NS": "Reliance Industries",
    "BHARTIARTL.NS": "Bharti Airtel",
    "LT.NS": "Larsen & Toubro",
    "INFY.NS": "Infosys",
    "SBIN.NS": "State Bank of India",
    "AXISBANK.NS": "Axis Bank",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "ITC.NS": "ITC",
}

# Main mode is Nifty 100. To restore the original scanner, change this to
# "WATCHLIST"; the existing WATCHLIST dictionary and scanning path are retained.
SCAN_UNIVERSE = "NIFTY100"  # Allowed values: "NIFTY100" or "WATCHLIST"
SCHEDULED_SCAN_URL = "https://raw.githubusercontent.com/blackparker123/quanttrading/daily-scan/daily_scan.json"

HISTORY_PERIOD = "2y"  # Gives enough daily candles for the 200-day average.
NIFTY_INDEX_SYMBOL = "^NSEI"
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_AVERAGE_PERIOD = 20
ATR_STOP_MULTIPLE = 2.0
BULL_TARGET_ATR = 4.0
BULL_SCALE_OUT_ATR = 2.0
DEFENSIVE_TARGET_ATR = 3.0
DEFENSIVE_SCALE_OUT_ATR = 1.5
PAPER_TIME_STOP_SESSIONS = 12
LIMITED_MODE_TOP_N = 3
LIMITED_MODE_PRICE_CEILING = 1000.0
LIMITED_MODE_DEFAULT_BUDGET = 16500.0
SCALE_OUT_FRACTION = 0.5
BUY_VOLUME_MULTIPLE = 1.2
ADX_MINIMUM = 20.0
CMF_PERIOD = 20
BACKTEST_DAYS = 252

st.set_page_config(page_title="QuantTrading | Nifty 50 Research", page_icon="📈", layout="wide")


@st.cache_data(ttl=900, show_spinner=False)
def download_history(symbol: str, auto_adjust: bool = True) -> pd.DataFrame:
    """Fetch daily OHLCV. Adjusted data is default; holdings can request raw closes."""
    data = yf.download(
        symbol,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=auto_adjust,
        multi_level_index=False,
        progress=False,
        threads=False,
        timeout=20,
    )
    if data is None or data.empty:
        raise ValueError("No daily data returned. The symbol may be unavailable or Yahoo may be limiting requests.")

    # Be tolerant of yfinance versions that return two-level column names.
    if isinstance(data.columns, pd.MultiIndex):
        fields = {"open", "high", "low", "close", "volume"}
        flattened = []
        for column in data.columns:
            match = next((str(part).strip().lower() for part in column if str(part).strip().lower() in fields), None)
            flattened.append(match.title() if match else str(column[-1]))
        data.columns = flattened
    else:
        data.columns = [str(column).strip().title() for column in data.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [name for name in required if name not in data.columns]
    if missing:
        raise ValueError(f"Price data is missing fields: {', '.join(missing)}")

    data = data[required].copy()
    data = data[~data.index.duplicated(keep="last")].sort_index()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=["Close"])


@st.cache_data(ttl=900, show_spinner=False)
def download_nifty_close() -> pd.Series:
    """Fetch Nifty 50 daily closes for the broad-market regime filter."""
    data = yf.download(
        NIFTY_INDEX_SYMBOL,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=True,
        multi_level_index=False,
        progress=False,
        threads=False,
        timeout=20,
    )
    if data is None or data.empty:
        raise ValueError("No Nifty 50 index data returned.")

    if isinstance(data.columns, pd.MultiIndex):
        close_column = next(
            (column for column in data.columns if any(str(part).strip().lower() == "close" for part in column)),
            None,
        )
        if close_column is None:
            raise ValueError("Nifty 50 index data has no Close field.")
        close = data[close_column]
    else:
        close_column = next((column for column in data.columns if str(column).strip().lower() == "close"), None)
        if close_column is None:
            raise ValueError("Nifty 50 index data has no Close field.")
        close = data[close_column]

    close = pd.to_numeric(close, errors="coerce").dropna()
    close.name = "Close"
    if close.empty:
        raise ValueError("Nifty 50 index closes are unavailable.")
    return close


@st.cache_data(ttl=900, show_spinner=False)
def download_scheduled_nifty100_scan() -> dict:
    """Read the latest background scan from the public data-only Git branch."""
    with urlopen(SCHEDULED_SCAN_URL, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("The scheduled Nifty 100 scan file is not valid.")
    return payload


@st.cache_data(ttl=900, show_spinner=False)
def scan_nifty100_cached(extra_symbols: tuple[str, ...] = (), max_price: float | None = None) -> dict:
    """Run the live Nifty 100 engine with optional custom tickers and a price ceiling."""
    nifty_close = download_nifty_close()
    scanner_parameters = inspect.signature(scan_nifty100).parameters
    if "extra_symbols" in scanner_parameters:
        scanner_kwargs = {}
        if "extra_symbols" in scanner_parameters:
            scanner_kwargs["extra_symbols"] = extra_symbols
        if "max_price" in scanner_parameters:
            scanner_kwargs["max_price"] = max_price
        payload = scan_nifty100(nifty_close, **scanner_kwargs)
    else:
        # A hosted process can briefly have the new dashboard and old engine loaded
        # together during a partial refresh. Keep serving the old one-argument engine.
        payload = scan_nifty100(nifty_close)
        payload["compatibility_notice"] = "The scanner engine is refreshing. Added sidebar symbols were evaluated by the dashboard compatibility path."

        regime = payload.get("market_regime", "Unavailable")
        existing = {row.get("Symbol"): row for row in payload.get("results", [])}
        for row in payload.get("results", []):
            row.setdefault("Universe", "Nifty 100")
            # The legacy engine only returned candidates after these filters passed.
            row.setdefault("Filter status", "Pass")

        errors = payload.setdefault("errors", [])
        for symbol in extra_symbols:
            if symbol in existing:
                existing[symbol]["Universe"] = "Added"
                continue
            try:
                candidate = evaluate(symbol, symbol.removesuffix(".NS"), 80.0, 0.5, 40.0, "Flexible score", regime)
                reasons = []
                if regime != "Bull":
                    reasons.append("Nifty 50 is below its 200-day SMA")
                if candidate["Price"] <= candidate["SMA200"]:
                    reasons.append("Price is at/below its 200-day SMA")
                if not 40 <= candidate["RSI (14)"] <= 70:
                    reasons.append("RSI is outside 40–70")
                eligible = not reasons
                target_multiple, scale_multiple = market_risk_parameters(regime)
                candidate.update({
                    "Universe": "Added",
                    "Filter status": "Pass" if eligible else "Filtered: " + "; ".join(reasons),
                    "Action": ("BUY" if candidate["Score"] >= 20 and 40 < candidate["RSI (14)"] < 70 else "WATCH") if eligible else "NOT ELIGIBLE",
                    "Reason": ("Passes Nifty alignment, SMA 200, and RSI 40–70. " if eligible else "Does not pass: " + "; ".join(reasons) + ". ") + candidate["Reason"],
                    "Target ATR multiple": float(target_multiple),
                    "Scale-out ATR multiple": float(scale_multiple),
                    "Scale-out level": candidate["Price"] + scale_multiple * candidate["ATR (14)"],
                    "Entry plan": "Next market open · TBD",
                    "Paper status": "User-added symbol · leaderboard research only",
                    "Paper entry": None,
                    "Paper regime": regime,
                    "Sessions held": None,
                })
                payload.setdefault("results", []).append(candidate)
                existing[symbol] = candidate
            except Exception as exc:
                errors.append({"Symbol": symbol, "Error": str(exc)[:160]})

        payload["eligible_count"] = sum(row.get("Filter status") == "Pass" for row in payload.get("results", []))
    if max_price is not None:
        payload["results"] = [
            row for row in payload.get("results", [])
            if pd.notna(row.get("Price")) and float(row["Price"]) < max_price
        ]
        payload["eligible_count"] = sum(row.get("Filter status") == "Pass" for row in payload["results"])
        if not payload["results"]:
            payload["message"] = f"No stocks below ₹{max_price:,.0f} passed the current market, SMA 200, and RSI filters."
    return payload


def get_market_regime() -> dict:
    """Classify the broad market using the latest Nifty 50 close and SMA 200."""
    try:
        close = download_nifty_close()
        if len(close) < 200:
            raise ValueError("At least 200 daily closes are needed for the Nifty 50 SMA.")
        sma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
        latest_close = float(close.iloc[-1])
        latest_sma200 = float(sma200)
        return {
            "name": "Bull" if latest_close > latest_sma200 else "Defensive",
            "close": latest_close,
            "sma200": latest_sma200,
            "date": pd.Timestamp(close.index[-1]).strftime("%d %b %Y"),
            "error": None,
        }
    except Exception as exc:
        return {"name": "Unavailable", "close": None, "sma200": None, "date": None, "error": str(exc)[:180]}


def market_risk_parameters(market_regime: str) -> tuple[float, float]:
    """Return final-target and half-position scale-out ATR multiples for a regime."""
    if market_regime == "Bull":
        return BULL_TARGET_ATR, BULL_SCALE_OUT_ATR
    return DEFENSIVE_TARGET_ATR, DEFENSIVE_SCALE_OUT_ATR


def evaluate_active_holding(ticker: str, entry_price: float, entry_date) -> dict:
    """Calculate fixed entry-ATR stop/target and the next-open portfolio command."""
    symbol = ticker.strip().upper()
    if symbol and "." not in symbol:
        symbol = f"{symbol}.NS"
    if not symbol:
        raise ValueError("Ticker is blank.")
    entry_ts = pd.Timestamp(pd.to_datetime(entry_date)).normalize()
    history = add_indicators(download_history(symbol, auto_adjust=False))
    latest = history.iloc[-1]
    latest_date = pd.Timestamp(history.index[-1]).normalize()
    if entry_ts > latest_date:
        raise ValueError("Entry date is after the latest available daily candle.")

    pre_entry = history.loc[history.index.normalize() < entry_ts]
    if pre_entry.empty or pd.isna(pre_entry.iloc[-1]["ATR"]):
        raise ValueError("No daily candle is available before the entry date to anchor ATR.")
    entry_atr = float(pre_entry.iloc[-1]["ATR"])
    signal_date = pd.Timestamp(pre_entry.index[-1])

    nifty = download_nifty_close()
    nifty_sma200 = nifty.rolling(200, min_periods=200).mean()
    nifty_before_entry = nifty.loc[nifty.index <= signal_date]
    if len(nifty_before_entry) < 200 or pd.isna(nifty_sma200.loc[nifty_before_entry.index[-1]]):
        raise ValueError("Nifty 50 history is too short to determine the regime at entry.")
    regime_date = nifty_before_entry.index[-1]
    regime = "Bull" if nifty_before_entry.iloc[-1] > nifty_sma200.loc[regime_date] else "Defensive"
    target_multiple, _ = market_risk_parameters(regime)

    fixed_stop = float(entry_price) - ATR_STOP_MULTIPLE * entry_atr
    fixed_target = float(entry_price) + target_multiple * entry_atr
    bars_since_entry = history.loc[history.index.normalize() >= entry_ts]
    sessions_held = len(bars_since_entry)
    outcome = "HOLD"
    outcome_date = None

    # Intraday order is unknowable from daily candles. If a candle touches both
    # levels, conservatively treat the hard stop as having triggered first.
    for bar_date, bar in bars_since_entry.iterrows():
        open_price = float(bar["Open"])
        low = float(bar["Low"])
        high = float(bar["High"])
        if open_price <= fixed_stop:
            outcome, outcome_date = "STOP HIT", pd.Timestamp(bar_date)
            break
        if open_price >= fixed_target:
            outcome, outcome_date = "TARGET HIT", pd.Timestamp(bar_date)
            break
        if low <= fixed_stop:
            outcome, outcome_date = "STOP HIT", pd.Timestamp(bar_date)
            break
        if high >= fixed_target:
            outcome, outcome_date = "TARGET HIT", pd.Timestamp(bar_date)
            break
    if outcome == "HOLD" and sessions_held >= PAPER_TIME_STOP_SESSIONS:
        outcome = "TIME STOP"

    current_close = float(latest["Close"])
    if outcome == "STOP HIT":
        command = f"🚨 STOP HIT — Price crossed the 2×ATR risk level ({money(fixed_stop)}) on {outcome_date:%d %b %Y}. Check whether your broker GTC stop triggered."
    elif outcome == "TARGET HIT":
        command = f"🎯 TARGET HIT — Stock reached {target_multiple:.0f}×ATR ({money(fixed_target)}) on {outcome_date:%d %b %Y}. Review closing the position and booking profit."
    elif outcome == "TIME STOP":
        command = f"⏱️ TIME STOP — The trade reached {PAPER_TIME_STOP_SESSIONS} trading sessions. The plan calls for a market exit at the next open."
    else:
        command = f"✅ HOLD — Current close is above the hard stop. Maintain GTC Stop at {money(fixed_stop)}."

    return {
        "Ticker": symbol,
        "Entry Price": float(entry_price),
        "Entry Date": entry_ts.date(),
        "Current Close": current_close,
        "As of": latest_date.date(),
        "Entry ATR": entry_atr,
        "Regime at Entry": regime,
        "Hard Stop": fixed_stop,
        "Final Target": fixed_target,
        "Sessions": sessions_held,
        "Status": outcome,
        "Tomorrow's Action": command,
    }


def render_active_portfolio() -> None:
    """Edit a session-private ledger and show entry-anchored risk commands."""
    st.subheader("Active Portfolio")
    st.caption(
        "After your broker confirms a fill, enter the ticker, actual entry price, and entry date below. "
        "This ledger is private to this browser session; download a CSV backup and reload it next time if needed."
    )

    ledger_columns = ["Ticker", "Entry Price", "Entry Date"]
    if "active_portfolio_ledger" not in st.session_state:
        st.session_state["active_portfolio_ledger"] = pd.DataFrame(columns=ledger_columns)

    with st.expander("Load a saved portfolio CSV"):
        uploaded = st.file_uploader("Choose a ledger backup", type=["csv"], key="portfolio_ledger_upload")
        if st.button("Load ledger", key="load_portfolio_ledger"):
            if uploaded is None:
                st.warning("Choose a CSV file first.")
            else:
                try:
                    incoming = pd.read_csv(uploaded)
                    missing = [column for column in ledger_columns if column not in incoming.columns]
                    if missing:
                        raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}.")
                    incoming = incoming[ledger_columns].copy()
                    incoming["Entry Price"] = pd.to_numeric(incoming["Entry Price"], errors="coerce")
                    incoming["Entry Date"] = pd.to_datetime(incoming["Entry Date"], errors="coerce").dt.date
                    st.session_state["active_portfolio_ledger"] = incoming
                    st.session_state.pop("active_portfolio_editor", None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not load this ledger: {str(exc)[:180]}")

    edited_ledger = st.data_editor(
        st.session_state["active_portfolio_ledger"],
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        key="active_portfolio_editor",
        column_config={
            "Ticker": st.column_config.TextColumn("Ticker (e.g. PNB or PNB.NS)"),
            "Entry Price": st.column_config.NumberColumn("Entry Price (₹)", min_value=0.01, step=0.05, format="₹%.2f"),
            "Entry Date": st.column_config.DateColumn("Entry Date", format="DD MMM YYYY"),
        },
    )
    st.session_state["active_portfolio_ledger"] = edited_ledger.copy()
    st.download_button(
        "Download ledger backup",
        data=edited_ledger.to_csv(index=False).encode("utf-8"),
        file_name="quanttrading_portfolio.csv",
        mime="text/csv",
        key="download_portfolio_ledger",
    )

    rows = []
    for _, item in edited_ledger.iterrows():
        ticker = str(item.get("Ticker", "")).strip()
        entry_price = pd.to_numeric(item.get("Entry Price"), errors="coerce")
        entry_date = item.get("Entry Date")
        if not ticker and pd.isna(entry_price) and pd.isna(entry_date):
            continue
        if not ticker or pd.isna(entry_price) or float(entry_price) <= 0 or pd.isna(entry_date):
            rows.append({
                "Ticker": ticker or "—",
                "Entry Price": None if pd.isna(entry_price) else float(entry_price),
                "Entry Date": entry_date,
                "Current Close": None,
                "Hard Stop": None,
                "Final Target": None,
                "Regime at Entry": "—",
                "Sessions": "—",
                "Status": "NEEDS INPUT",
                "Tomorrow's Action": "⚪ NEEDS INPUT — Complete ticker, entry price, and entry date.",
            })
            continue
        try:
            rows.append(evaluate_active_holding(ticker, float(entry_price), entry_date))
        except Exception as exc:
            normalized_ticker = ticker.upper()
            if "." not in normalized_ticker:
                normalized_ticker += ".NS"
            rows.append({
                "Ticker": normalized_ticker,
                "Entry Price": float(entry_price),
                "Entry Date": pd.Timestamp(entry_date).date(),
                "Current Close": None,
                "As of": None,
                "Entry ATR": None,
                "Regime at Entry": "—",
                "Hard Stop": None,
                "Final Target": None,
                "Sessions": "—",
                "Status": "NEEDS DATA",
                "Tomorrow's Action": f"⚪ NEEDS DATA — {str(exc)[:150]}",
            })

    if rows:
        result = pd.DataFrame(rows)
        table = result[["Ticker", "Entry Price", "Entry Date", "Current Close", "As of", "Hard Stop", "Final Target", "Regime at Entry", "Sessions", "Status", "Tomorrow's Action"]].copy()
        for column in ("Entry Price", "Current Close", "Hard Stop", "Final Target"):
            table[column] = table[column].map(money)
        status_colors = {
            "HOLD": "#e7f5e9",
            "TARGET HIT": "#fff2cc",
            "STOP HIT": "#fde2e2",
            "TIME STOP": "#f7d9e3",
            "NEEDS INPUT": "#eeeeee",
            "NEEDS DATA": "#eeeeee",
        }
        styled = table.style.apply(
            lambda row: [
                f"background-color: {status_colors.get(row['Status'], '#ffffff')}; font-weight: 600;" if column == "Tomorrow's Action" else ""
                for column in row.index
            ],
            axis=1,
        )
        st.dataframe(styled, hide_index=True, width="stretch", height=min(620, 46 + 44 * len(table)))
    else:
        st.info("Add a filled position to the ledger to see its stop, target, session count, and next-open action.")

    st.caption(
        "Stops and targets use the entry price plus ATR from the last available candle before entry; regime is also fixed from that date. "
        "A daily candle touching both stop and target is treated as a stop first. Gaps, liquidity, and broker execution can differ; verify orders in your broker."
    )


@st.cache_data(ttl=86400, show_spinner=False)
def download_pe(symbol: str) -> float | None:
    """Return Yahoo's trailing P/E when available; valuation data can be missing."""
    try:
        value = yf.Ticker(symbol).info.get("trailingPE")
        return float(value) if value is not None and pd.notna(value) else None
    except Exception:
        return None


def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """Add trend, momentum, volume, and volatility measures to a price frame."""
    result = data.copy()
    close = result["Close"]

    for period in (20, 50, 200):
        result[f"SMA{period}"] = close.rolling(period, min_periods=period).mean()

    change = close.diff()
    average_gain = change.clip(lower=0).ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    average_loss = (-change.clip(upper=0)).ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    result["RSI"] = 100 - (100 / (1 + relative_strength))
    result.loc[(average_loss == 0) & (average_gain > 0), "RSI"] = 100
    result.loc[(average_loss == 0) & (average_gain == 0), "RSI"] = 50

    ema12 = close.ewm(span=12, min_periods=12, adjust=False).mean()
    ema26 = close.ewm(span=26, min_periods=26, adjust=False).mean()
    result["MACD"] = ema12 - ema26
    result["MACD Signal"] = result["MACD"].ewm(span=9, min_periods=9, adjust=False).mean()

    previous_close = close.shift(1)
    true_range = pd.concat(
        [result["High"] - result["Low"], (result["High"] - previous_close).abs(), (result["Low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    result["ATR"] = true_range.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean()
    result["Volume Avg"] = result["Volume"].rolling(VOLUME_AVERAGE_PERIOD, min_periods=VOLUME_AVERAGE_PERIOD).mean()

    # Bollinger Bands: 20-day mean plus/minus two rolling standard deviations.
    rolling_std = close.rolling(20, min_periods=20).std(ddof=0)
    result["BB Upper"] = result["SMA20"] + 2 * rolling_std
    result["BB Lower"] = result["SMA20"] - 2 * rolling_std
    band_width = (result["BB Upper"] - result["BB Lower"]).replace(0, float("nan"))
    result["BB %B"] = (close - result["BB Lower"]) / band_width

    # ADX (14): Wilder-smoothed directional movement divided by true range.
    up_move = result["High"].diff()
    down_move = -result["Low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_smooth = true_range.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean() / atr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean() / atr_smooth
    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    result["ADX"] = dx.ewm(alpha=1 / ATR_PERIOD, min_periods=ATR_PERIOD, adjust=False).mean()

    # CMF (20): positive values mean more volume traded near daily highs.
    day_range = (result["High"] - result["Low"]).replace(0, float("nan"))
    money_flow_multiplier = ((close - result["Low"]) - (result["High"] - close)) / day_range
    money_flow_volume = money_flow_multiplier.fillna(0) * result["Volume"]
    result["CMF"] = money_flow_volume.rolling(CMF_PERIOD, min_periods=CMF_PERIOD).sum() / result["Volume"].rolling(CMF_PERIOD, min_periods=CMF_PERIOD).sum().replace(0, float("nan"))

    # One-year buy-and-hold history statistics, shown as context rather than strategy results.
    daily_returns = close.pct_change().dropna().tail(BACKTEST_DAYS)
    result["Sharpe 1Y"] = float("nan")
    result["Max DD 1Y %"] = float("nan")
    if len(daily_returns) > 1 and daily_returns.std(ddof=1) > 0:
        result.loc[result.index[-1], "Sharpe 1Y"] = (daily_returns.mean() / daily_returns.std(ddof=1)) * (252 ** 0.5)
        equity = (1 + daily_returns).cumprod()
        drawdown = equity / equity.cummax() - 1
        result.loc[result.index[-1], "Max DD 1Y %"] = drawdown.min() * 100
    return result


def weighted_score(factors: list[tuple[str, int, float]]) -> tuple[int, str, str]:
    """Return a directional score (-100 to +100), rating, and readable drivers."""
    available_weight = sum(weight for _, weight, _ in factors)
    if not available_weight:
        return 0, "Hold", "No score inputs were available."

    score = round(100 * sum(weight * direction for _, weight, direction in factors) / available_weight)
    if score >= 55:
        rating = "Strong Buy"
    elif score >= 20:
        rating = "Buy"
    elif score > -20:
        rating = "Hold"
    elif score > -55:
        rating = "Sell"
    else:
        rating = "Strong Sell"

    active = [(name, round(weight * direction)) for name, weight, direction in factors if direction]
    active.sort(key=lambda item: abs(item[1]), reverse=True)
    if active:
        drivers = "; ".join(f"{name} ({points:+d})" for name, points in active[:5])
        reason = f"Weighted score {score:+d}/100. Main score drivers: {drivers}."
    else:
        reason = f"Weighted score {score:+d}/100; the available indicators are mostly neutral."
    return score, rating, reason


def evaluate(
    symbol: str,
    company: str,
    max_pe: float,
    min_sharpe: float,
    max_drawdown_pct: float,
    signal_mode: str,
    market_regime: str,
) -> dict:
    """Score indicators or apply the visible rules, then calculate ATR-based levels."""
    history = add_indicators(download_history(symbol))
    last = history.iloc[-1]
    fields = ["Close", "SMA20", "SMA50", "SMA200", "RSI", "MACD", "MACD Signal", "ATR", "Volume", "Volume Avg", "ADX", "CMF", "BB Upper"]
    if any(pd.isna(last[field]) for field in fields) or last["ATR"] <= 0:
        raise ValueError("Not enough clean daily history to calculate all indicators and risk levels.")

    price = float(last["Close"])
    open_price = float(last["Open"])
    sma20, sma50, sma200 = (float(last[name]) for name in ("SMA20", "SMA50", "SMA200"))
    rsi = float(last["RSI"])
    macd, macd_signal = float(last["MACD"]), float(last["MACD Signal"])
    atr = float(last["ATR"])
    volume_ratio = float(last["Volume"] / last["Volume Avg"]) if last["Volume Avg"] else 0.0
    adx = float(last["ADX"])
    cmf = float(last["CMF"])
    bb_percent_b = float(last["BB %B"]) if pd.notna(last["BB %B"]) else float("nan")
    sharpe_1y = float(last["Sharpe 1Y"]) if pd.notna(last["Sharpe 1Y"]) else None
    max_dd_1y_pct = float(last["Max DD 1Y %"]) if pd.notna(last["Max DD 1Y %"]) else None
    pe = download_pe(symbol)
    target_atr_multiple, scale_out_atr_multiple = market_risk_parameters(market_regime)

    pe_ok = max_pe <= 0 or pe is None or (0 < pe <= max_pe)
    sharpe_ok = sharpe_1y is None or sharpe_1y >= min_sharpe
    drawdown_ok = max_dd_1y_pct is None or max_dd_1y_pct >= -max_drawdown_pct
    rsi_buy_ceiling = 80 if adx > 25 else 75

    buy_checks = {
        "Price above 20-day average": price > sma20,
        "20-day average above 50-day": sma20 > sma50,
        "50-day average above 200-day": sma50 > sma200,
        "MACD above signal": macd > macd_signal,
        "RSI is strictly between 40 and 70": 40 < rsi < 70,
        f"Volume at least {BUY_VOLUME_MULTIPLE:.1f}× its 20-day average": volume_ratio >= BUY_VOLUME_MULTIPLE,
        f"ADX confirms trend (≥ {ADX_MINIMUM:.0f})": adx >= ADX_MINIMUM,
        "CMF confirms positive volume flow": cmf > 0,
        "Bollinger %B is no higher than 1.10": pd.notna(bb_percent_b) and bb_percent_b <= 1.10,
        f"1Y Sharpe meets minimum ({min_sharpe:.1f})": sharpe_ok,
        f"1Y max drawdown is within {max_drawdown_pct:.0f}%": drawdown_ok,
        f"Trailing P/E is positive and ≤ {max_pe:.0f}, when available": pe_ok,
    }
    watch_ok = price > sma50 > sma200 and macd > macd_signal and 40 <= rsi <= 75 and cmf > -0.05
    factors: list[tuple[str, int, float]] = [
        ("Price vs SMA 20", 10, 1.0 if price > sma20 else -1.0),
        ("SMA 20 vs SMA 50", 10, 1.0 if sma20 > sma50 else -1.0),
        ("SMA 50 vs SMA 200", 10, 1.0 if sma50 > sma200 else -1.0),
        ("MACD vs signal", 12, 1.0 if macd > macd_signal else -1.0),
    ]
    if 50 <= rsi <= 70:
        rsi_signal = 1.0
    elif 70 < rsi <= rsi_buy_ceiling:
        rsi_signal = 0.6
    elif 45 <= rsi < 50:
        rsi_signal = -0.2
    elif 35 <= rsi < 45:
        rsi_signal = -0.6
    else:
        rsi_signal = -1.0
    factors.append(("RSI", 10, rsi_signal))
    factors.append(("High-volume candle", 8, (1.0 if price >= open_price else -1.0) if volume_ratio >= BUY_VOLUME_MULTIPLE else 0.0))
    adx_signal = (1.0 if price > sma50 else -1.0) if adx >= 25 else ((0.5 if price > sma50 else -0.5) if adx >= ADX_MINIMUM else 0.0)
    factors.append(("ADX trend strength", 8, adx_signal))
    cmf_signal = 1.0 if cmf > 0.05 else (0.5 if cmf > 0 else (-1.0 if cmf < -0.05 else (-0.5 if cmf < 0 else 0.0)))
    factors.append(("CMF money flow", 8, cmf_signal))
    if pd.notna(bb_percent_b):
        bb_signal = -1.0 if bb_percent_b > 1.10 else (0.5 if 0.7 <= bb_percent_b <= 1.10 else (0.0 if 0.3 <= bb_percent_b < 0.7 else (-0.5 if bb_percent_b <= 0.1 else -0.2)))
        factors.append(("Bollinger position", 8, bb_signal))
    if sharpe_1y is not None:
        sharpe_signal = 1.0 if sharpe_1y >= min_sharpe + 0.5 else (0.5 if sharpe_1y >= min_sharpe else -1.0)
        factors.append(("1Y Sharpe", 6, sharpe_signal))
    if max_dd_1y_pct is not None:
        drawdown_limit = -max_drawdown_pct
        drawdown_signal = 1.0 if max_dd_1y_pct >= drawdown_limit + 15 else (0.5 if max_dd_1y_pct >= drawdown_limit else -1.0)
        factors.append(("1Y maximum drawdown", 6, drawdown_signal))
    if max_pe > 0 and pe is not None:
        pe_signal = -1.0 if pe <= 0 else (0.5 if pe <= max_pe else -0.5)
        factors.append(("Trailing P/E filter", 4, pe_signal))
    score, rating, score_reason = weighted_score(factors)
    buy_checks["Directional score is at least +20"] = score >= 20

    if signal_mode == "Flexible score":
        rsi_entry_ok = 40 < rsi < 70
        action = "BUY" if score >= 20 and rsi_entry_ok else ("SELL" if score <= -20 else "HOLD")
        reason = score_reason + " BUY requires score ≥+20 and RSI strictly between 40 and 70; SELL starts at −20."
        if score >= 20 and not rsi_entry_ok:
            reason += " The score is bullish, but RSI is outside the BUY entry range."
        stop = target = None
    elif all(buy_checks.values()):
        action = "BUY"
        reason = "Trend, momentum, volatility, volume-flow, valuation, and historical-risk filters all pass."
        stop = price - ATR_STOP_MULTIPLE * atr
        target = price + target_atr_multiple * atr
    elif watch_ok:
        action = "HOLD"
        failed = [name for name, passed in buy_checks.items() if not passed]
        reason = "Long-term trend and momentum pass; BUY filters still missing: " + "; ".join(failed) + "."
        stop = target = None
    else:
        action = "SELL" if price < sma50 and macd < macd_signal and adx >= ADX_MINIMUM and cmf < 0 else "NO ACTION"
        failed = []
        if price <= sma50:
            failed.append("price is not above the 50-day average")
        if sma50 <= sma200:
            failed.append("50-day average is not above the 200-day average")
        if macd <= macd_signal:
            failed.append("MACD is not above its signal")
        if adx < ADX_MINIMUM:
            failed.append(f"ADX ({adx:.1f}) is below the trend threshold")
        if cmf >= 0:
            failed.append("CMF does not show negative volume flow")
        if not 40 <= rsi <= 75:
            failed.append(f"RSI ({rsi:.1f}) is outside the 40–75 watch range")
        reason = "; ".join(failed) or "The BUY and WATCH rules are not met."
        stop = target = None

    if action == "BUY" and market_regime == "Unavailable":
        action = "NO ACTION"
        reason += " Nifty 50 regime is unavailable, so no BUY is allowed until the market filter can be calculated."

    # Always show a comparable ATR scenario. SELL uses a hypothetical short;
    # BUY, HOLD, and NO ACTION use an illustrative long scenario.
    scenario = "Short" if action == "SELL" else "Long"
    if stop is None:
        if scenario == "Short":
            stop = price + ATR_STOP_MULTIPLE * atr
            target = price - target_atr_multiple * atr
        else:
            stop = price - ATR_STOP_MULTIPLE * atr
            target = price + target_atr_multiple * atr

    risk_pct = (abs(price - stop) / price * 100) if stop is not None else None
    reward_pct = (abs(target - price) / price * 100) if target is not None else None
    date = pd.Timestamp(history.index[-1]).strftime("%d %b %Y")
    return {
        "Symbol": symbol, "Company": company, "Date": date, "Action": action, "Rating": rating,
        "Score": score, "Scenario": scenario, "Reason": reason, "Market regime": market_regime,
        "Target ATR multiple": target_atr_multiple, "Scale-out ATR multiple": scale_out_atr_multiple,
        "Price": price, "Stop loss": stop, "Target": target, "Risk %": risk_pct,
        "Reward %": reward_pct, "RSI (14)": rsi, "Trend": "Bullish" if price > sma50 > sma200 else "Mixed / weak",
        "Volume vs avg": volume_ratio, "SMA20": sma20, "SMA50": sma50, "SMA200": sma200,
        "MACD": macd, "MACD Signal": macd_signal, "ATR (14)": atr, "ADX (14)": adx,
        "CMF (20)": cmf, "BB %B": bb_percent_b, "P/E": pe,
        "Sharpe 1Y": sharpe_1y, "Max DD 1Y %": max_dd_1y_pct,
        "Reward/Risk": target_atr_multiple / ATR_STOP_MULTIPLE,
    }


def update_paper_positions(results: list[dict], signal_mode: str) -> None:
    """Track regime-based paper entries, partial exits, and session time stops."""
    positions = st.session_state.setdefault("paper_positions", {})
    closed_trades = st.session_state.setdefault("paper_trades", [])

    # Keep already-open Update 4 positions on the management rules they entered with.
    for saved_position in positions.values():
        saved_position.setdefault("management_version", 4)
        saved_position.setdefault("time_stop_sessions", PAPER_TIME_STOP_SESSIONS)
        saved_position.setdefault("market_regime", "Update 2 legacy")
        saved_position.setdefault("target_atr_multiple", BULL_TARGET_ATR)
        saved_position.setdefault("breakeven_trigger_atr", 2.5)
        entry_atr = saved_position.get("entry_atr")
        if entry_atr and saved_position.get("status") == "active":
            if "target" in saved_position and "entry_price" in saved_position:
                saved_position["target_atr_multiple"] = (
                    saved_position["target"] - saved_position["entry_price"]
                ) / entry_atr
            if "breakeven_trigger" in saved_position and "entry_price" in saved_position:
                saved_position["breakeven_trigger_atr"] = (
                    saved_position["breakeven_trigger"] - saved_position["entry_price"]
                ) / entry_atr

    for result in results:
        symbol = result["Symbol"]
        history = add_indicators(download_history(symbol))
        latest_date = pd.Timestamp(history.index[-1])
        position = positions.get(symbol)
        if position is None and result["Action"] == "BUY":
            position = {
                "status": "pending",
                "signal_date": latest_date,
                "entry_atr": float(result["ATR (14)"]),
                "mode": signal_mode,
                "market_regime": result["Market regime"],
                "target_atr_multiple": float(result["Target ATR multiple"]),
                "scale_out_atr_multiple": float(result["Scale-out ATR multiple"]),
                "scale_out_fraction": SCALE_OUT_FRACTION,
                "scale_out_done": False,
                "partial_exit_price": None,
                "sessions_held": 0,
                "time_stop_sessions": PAPER_TIME_STOP_SESSIONS,
                "management_version": 5,
            }
            positions[symbol] = position

        if position is None:
            result["Paper status"] = "No paper position"
            result["Paper entry"] = None
            result["Paper regime"] = None
            result["Sessions held"] = None
            continue

        if position["status"] == "active" and "sessions_held" not in position:
            through_date = position.get("last_processed_date", latest_date)
            entry_date = pd.Timestamp(position["entry_date"])
            through_date = pd.Timestamp(through_date)
            position["sessions_held"] = int(((history.index >= entry_date) & (history.index <= through_date)).sum())
        position.setdefault("sessions_held", 0)

        signal_date = position["signal_date"]
        bars = history.loc[history.index > signal_date]
        if position["status"] == "active" and position.get("last_processed_date") is not None:
            bars = history.loc[history.index > position["last_processed_date"]]

        closed_reason = None
        for bar_date, bar in bars.iterrows():
            entered_this_bar = False
            if position["status"] == "pending":
                entry = float(bar["Open"])
                entry_atr = position["entry_atr"]
                initial_stop = entry - ATR_STOP_MULTIPLE * entry_atr
                new_entry_fields = {
                    "status": "active",
                    "entry_price": entry,
                    "entry_date": pd.Timestamp(bar_date),
                    "initial_stop": initial_stop,
                    "stop": initial_stop,
                    "target": entry + position["target_atr_multiple"] * entry_atr,
                    "breakeven_active": False,
                    "last_processed_date": pd.Timestamp(signal_date),
                    "sessions_held": 1,
                }
                if position.get("management_version", 4) >= 5:
                    new_entry_fields.update({
                        "scale_out_trigger": entry + position["scale_out_atr_multiple"] * entry_atr,
                        "scale_out_done": False,
                        "scale_out_price": None,
                    })
                else:
                    new_entry_fields["breakeven_trigger"] = entry + position["breakeven_trigger_atr"] * entry_atr
                position.update(new_entry_fields)
                entered_this_bar = True

            queued_exit_at_open = position.get("pending_exit") and bar_date > position["pending_exit_date"]
            if not entered_this_bar and not queued_exit_at_open:
                position["sessions_held"] = position.get("sessions_held", 0) + 1

            open_price = float(bar["Open"])
            low = float(bar["Low"])
            high = float(bar["High"])
            exit_price = None
            closed_reason = None
            if position.get("pending_exit") and bar_date > position["pending_exit_date"]:
                exit_price = open_price
                closed_reason = position.get("pending_exit_reason", "SELL signal · next session open")
            elif open_price <= position["stop"]:
                exit_price = open_price
                closed_reason = "Gap through breakeven stop after scale-out" if position.get("scale_out_done") else "Gap through stop"
            elif open_price >= position["target"]:
                if position.get("management_version", 4) >= 5 and not position.get("scale_out_done"):
                    position["scale_out_done"] = True
                    position["scale_out_price"] = position["scale_out_trigger"]
                    position["stop"] = position["entry_price"]
                    position["breakeven_active"] = True
                exit_price = position["target"]
                closed_reason = "Target reached after 50% scale-out" if position.get("scale_out_done") else "Target reached"
            elif low <= position["stop"]:
                exit_price = position["stop"]
                if position.get("scale_out_done"):
                    closed_reason = "Breakeven stop after 50% scale-out"
                else:
                    closed_reason = "Breakeven stop" if position["breakeven_active"] else "Initial ATR stop"
            elif position.get("management_version", 4) >= 5:
                if not position.get("scale_out_done") and high >= position["scale_out_trigger"]:
                    position["scale_out_done"] = True
                    position["scale_out_price"] = position["scale_out_trigger"]
                    position["stop"] = position["entry_price"]
                    position["breakeven_active"] = True
                    if low <= position["stop"]:
                        exit_price = position["stop"]
                        closed_reason = "Breakeven stop after 50% scale-out"
                    elif high >= position["target"]:
                        exit_price = position["target"]
                        closed_reason = "Target reached after 50% scale-out"
                elif high >= position["target"]:
                    exit_price = position["target"]
                    closed_reason = "Target reached after 50% scale-out" if position.get("scale_out_done") else "Target reached"
            elif not position["breakeven_active"] and high >= position["breakeven_trigger"]:
                position["stop"] = position["entry_price"]
                position["breakeven_active"] = True
                if low <= position["stop"]:
                    exit_price = position["stop"]
                    closed_reason = "Breakeven stop after intraday trigger"
                elif high >= position["target"]:
                    exit_price = position["target"]
                    closed_reason = "Target reached"
            elif high >= position["target"]:
                exit_price = position["target"]
                closed_reason = "Target reached"

            position["last_processed_date"] = pd.Timestamp(bar_date)
            if exit_price is not None:
                entry = position["entry_price"]
                initial_risk = entry - position["initial_stop"]
                partial_fraction = position.get("scale_out_fraction", SCALE_OUT_FRACTION) if position.get("scale_out_done") else 0.0
                remaining_fraction = 1.0 - partial_fraction
                partial_price = position.get("scale_out_price")
                return_fraction = remaining_fraction * (exit_price / entry - 1)
                if partial_fraction and partial_price is not None:
                    return_fraction += partial_fraction * (partial_price / entry - 1)
                closed_trades.append({
                    "Symbol": symbol,
                    "Mode": position["mode"],
                    "Market regime": position["market_regime"],
                    "Entry date": position["entry_date"].strftime("%d %b %Y"),
                    "Exit date": pd.Timestamp(bar_date).strftime("%d %b %Y"),
                    "Entry": entry,
                    "Exit": exit_price,
                    "Scale-out price": partial_price,
                    "Scale-out fraction": partial_fraction,
                    "Sessions held": position.get("sessions_held", 0),
                    "Return %": return_fraction * 100,
                    "Result R": (return_fraction * entry) / initial_risk,
                    "Target ATR": position["target_atr_multiple"],
                    "Scale-out ATR": position.get("scale_out_atr_multiple"),
                    "Exit reason": closed_reason,
                })
                positions.pop(symbol, None)
                position = None
                break

            if position["sessions_held"] >= position.get("time_stop_sessions", PAPER_TIME_STOP_SESSIONS) and not position.get("pending_exit"):
                position["pending_exit"] = True
                position["pending_exit_date"] = pd.Timestamp(bar_date)
                position["pending_exit_reason"] = f"{position['time_stop_sessions']}-session time stop · next open"

        if position is None:
            result["Paper status"] = f"Closed: {closed_reason}"
            result["Paper entry"] = None
            result["Paper regime"] = None
            continue

        if (
            position["status"] == "active"
            and position["mode"] == signal_mode
            and result["Action"] == "SELL"
            and not position.get("pending_exit")
        ):
            position["pending_exit"] = True
            position["pending_exit_date"] = latest_date
            position["pending_exit_reason"] = "SELL signal · next session open"

        if (
            position["status"] == "active"
            and position.get("sessions_held", 0) >= position.get("time_stop_sessions", PAPER_TIME_STOP_SESSIONS)
            and not position.get("pending_exit")
        ):
            position["pending_exit"] = True
            position["pending_exit_date"] = latest_date
            position["pending_exit_reason"] = f"{position['time_stop_sessions']}-session time stop · next open"

        if position["status"] == "pending":
            result["Paper status"] = "Entry queued · next session open"
            result["Paper entry"] = None
            result["Paper regime"] = position["market_regime"]
        else:
            if position.get("pending_exit"):
                result["Paper status"] = f"Exit queued · {position.get('pending_exit_reason', 'next session open')}"
            else:
                result["Paper status"] = "Active · 50% scaled out" if position.get("scale_out_done") else "Active"
            result["Paper entry"] = position["entry_price"]
            result["Paper regime"] = position["market_regime"]
            result["Target ATR multiple"] = position["target_atr_multiple"]
            result["Scale-out ATR multiple"] = position.get("scale_out_atr_multiple", position.get("breakeven_trigger_atr", 2.5))
            result["Stop loss"] = position["stop"]
            result["Target"] = position["target"]
            result["Risk %"] = max(position["entry_price"] - position["stop"], 0) / position["entry_price"] * 100
            result["Reward %"] = (position["target"] - position["entry_price"]) / position["entry_price"] * 100
            result["Reward/Risk"] = (position["target"] - position["entry_price"]) / (position["entry_price"] - position["initial_stop"])
            result["Sessions held"] = position.get("sessions_held", 0)
            result["Scale-out done"] = bool(position.get("scale_out_done"))


def money(value):
    return "—" if value is None or pd.isna(value) else f"₹{value:,.2f}"


def make_candlestick_chart(data: pd.DataFrame, show_sma20: bool, show_sma50: bool, show_sma200: bool, show_bollinger: bool):
    """Create a readable daily candlestick chart with optional overlays and volume."""
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.76, 0.24],
    )
    dates = data.index
    figure.add_trace(
        go.Candlestick(
            x=dates,
            open=data["Open"],
            high=data["High"],
            low=data["Low"],
            close=data["Close"],
            name="Daily candles",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
            increasing_fillcolor="#16a34a",
            decreasing_fillcolor="#dc2626",
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    overlays = [
        (show_sma20, "SMA20", "#2563eb", "solid"),
        (show_sma50, "SMA50", "#f59e0b", "solid"),
        (show_sma200, "SMA200", "#7c3aed", "dash"),
    ]
    for enabled, column, color, dash in overlays:
        if enabled:
            figure.add_trace(
                go.Scatter(x=dates, y=data[column], name=column, mode="lines", line={"color": color, "width": 1.5, "dash": dash}),
                row=1,
                col=1,
            )
    if show_bollinger:
        figure.add_trace(
            go.Scatter(x=dates, y=data["BB Upper"], name="Bollinger upper", mode="lines", line={"color": "#64748b", "width": 1, "dash": "dot"}),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Scatter(x=dates, y=data["BB Lower"], name="Bollinger lower", mode="lines", line={"color": "#64748b", "width": 1, "dash": "dot"}),
            row=1,
            col=1,
        )

    volume_colors = ["#16a34a" if close >= open_ else "#dc2626" for open_, close in zip(data["Open"], data["Close"])]
    figure.add_trace(
        go.Bar(x=dates, y=data["Volume"], name="Volume", marker_color=volume_colors, opacity=0.7),
        row=2,
        col=1,
    )
    figure.update_layout(
        height=650,
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        xaxis={"rangeselector": {"buttons": [
            {"count": 1, "label": "1m", "step": "month", "stepmode": "backward"},
            {"count": 3, "label": "3m", "step": "month", "stepmode": "backward"},
            {"count": 6, "label": "6m", "step": "month", "stepmode": "backward"},
            {"count": 1, "label": "1y", "step": "year", "stepmode": "backward"},
            {"step": "all", "label": "2y"},
        ]}},
    )
    figure.update_yaxes(title_text="Price (₹)", row=1, col=1, fixedrange=False)
    figure.update_yaxes(title_text="Volume", row=2, col=1, fixedrange=False)
    figure.update_xaxes(rangeslider_visible=False, row=1, col=1)
    return figure


def main() -> None:
    full_list_view = st.query_params.get("view") == "all"
    query_symbols = st.query_params.get("symbols", "")
    account_size_default = st.session_state.get(
        "account_size",
        "Under ₹2L" if st.query_params.get("portfolio") == "limited" else "Standard",
    )
    active_symbols = st.session_state.get("custom_symbols_input", "") or query_symbols
    link_params = {"view": "all"}
    if active_symbols.strip():
        link_params["symbols"] = active_symbols
    if account_size_default == "Under ₹2L":
        link_params["portfolio"] = "limited"
    full_list_url = "?" + urlencode(link_params)
    header_left, header_right = st.columns([5, 2])
    header_left.title("📈 QuantTrading")
    if SCAN_UNIVERSE == "NIFTY100":
        if full_list_view:
            header_right.markdown(
                '<a href="/" style="display:block;text-align:right;padding:0.5rem 0;">← Back to dashboard</a>',
                unsafe_allow_html=True,
            )
        else:
            header_right.markdown(
                f'<a href="{full_list_url}" target="_blank" rel="noopener noreferrer" '
                'style="display:block;text-align:right;padding:0.5rem 0;">View all passing stocks ↗</a>',
                unsafe_allow_html=True,
            )
    st.caption("Indian cash-equity swing research · Daily data · No order placement")
    st.info(
        "Signals are indicator-based research outputs from recent market data, not personalized financial advice. "
        "Check the reason, data date, and your own risk limits before making any decision."
    )

    with st.sidebar:
        st.header("Scanner")
        if SCAN_UNIVERSE == "NIFTY100":
            account_size = st.radio(
                "Account Size",
                ("Under ₹2L", "Standard"),
                index=0 if account_size_default == "Under ₹2L" else 1,
                key="account_size",
                help="Under ₹2L enables a Top 3 screen, a per-stock budget input, whole-share estimates, and a single stop/target plan. It places no orders.",
            )
            limited_portfolio_mode = account_size == "Under ₹2L"
            if limited_portfolio_mode:
                st.caption("Limited Portfolio Growth · Top 3 · price below ₹1,000 · single-target plan")
                per_stock_budget = st.number_input(
                    "Budget per stock (₹)",
                    min_value=1000.0,
                    max_value=199999.0,
                    value=LIMITED_MODE_DEFAULT_BUDGET,
                    step=500.0,
                    help="Default is ₹16,500 per candidate. Up to three candidates use this amount; unused budgets remain cash.",
                )
            signal_mode = "Flexible score"
            st.caption("The Nifty 100 leaderboard always ranks by the Flexible Directional Score.")
            st.write("Main scanner: Nifty 100 leaderboard. To return to the original 10-stock list, change `SCAN_UNIVERSE` near the top of `main.py` to `WATCHLIST`.")
            max_pe, min_sharpe, max_drawdown_pct = 60.0, 0.0, 50
            st.caption("Score settings: P/E reference ceiling 80, preferred 1Y Sharpe ≥ 0.5, preferred historical drawdown ≤ 40%.")
        else:
            account_size = "Standard"
            limited_portfolio_mode = False
            per_stock_budget = LIMITED_MODE_DEFAULT_BUDGET
            signal_mode = st.selectbox(
                "Signal mode",
                ("Flexible score", "Strict rules"),
                help="Flexible score combines bullish and bearish indicator evidence. Strict rules keeps the all-checks-must-pass BUY logic.",
            )
            st.write("Original 10-stock scanner mode is active.")
            max_pe = st.number_input("Maximum trailing P/E (0 disables)", min_value=0.0, max_value=300.0, value=60.0, step=5.0)
            min_sharpe = st.number_input("Minimum 1Y Sharpe", min_value=-2.0, max_value=3.0, value=0.0, step=0.1)
            max_drawdown_pct = st.slider("Maximum historical drawdown", min_value=10, max_value=80, value=50)
        with st.form("custom_watchlist"):
            added_symbols = st.text_input(
                "Add your own Yahoo Finance symbols",
                placeholder="WIPRO.NS, TATAMOTORS.NS",
                help="Enter one or more Yahoo Finance symbols separated by commas. NSE shares can be entered as TCS or TCS.NS. In Nifty 100 mode, these stocks are added to the leaderboard.",
                key="custom_symbols_input",
            )
            st.form_submit_button("Apply symbols")
        if st.button("Refresh market data", type="primary", width="stretch"):
            download_history.clear()
            download_nifty_close.clear()
            download_scheduled_nifty100_scan.clear()
            scan_nifty100_cached.clear()
            st.rerun()
        st.caption("Cached for 15 minutes. Yahoo Finance may return delayed, missing, or unavailable data.")
        if SCAN_UNIVERSE != "NIFTY100":
            st.subheader("BUY filters")

    market = get_market_regime()
    market_columns = st.columns([1, 2])
    market_columns[0].metric("Nifty 50 regime", market["name"])
    if market["name"] != "Unavailable":
        if limited_portfolio_mode:
            market_columns[1].caption(
                f"Nifty 50 close {market['close']:,.2f} vs. 200-day SMA {market['sma200']:,.2f} on {market['date']}. "
                "Limited mode uses one 2×ATR stop and one final target: +4×ATR in Bull mode or +3×ATR in Defensive mode."
            )
        else:
            market_columns[1].caption(
                f"Nifty 50 close {market['close']:,.2f} vs. 200-day SMA {market['sma200']:,.2f} "
                f"on {market['date']}. Bull mode scales out 50% at +2× ATR, then targets +4× ATR; "
                "Defensive mode scales out 50% at +1.5× ATR, then targets +3× ATR. After scale-out, "
                "the remaining stop moves to entry."
            )
    else:
        st.warning(f"Nifty 50 regime data is unavailable: {market['error']} BUY setups are paused until it loads.")

    leaderboard_mode = SCAN_UNIVERSE == "NIFTY100"
    scan_payload = None
    if leaderboard_mode:
        requested_symbols = ",".join(part for part in (added_symbols, query_symbols) if part.strip())
        extra_symbols = tuple(dict.fromkeys(
            (symbol.strip().upper() + ".NS") if symbol.strip() and "." not in symbol.strip()
            else symbol.strip().upper()
            for symbol in requested_symbols.split(",") if symbol.strip()
        ))
        market_date = pd.to_datetime(market["date"]).strftime("%Y-%m-%d") if market.get("date") else None
        with st.spinner("Loading the Nifty 100 scan and your added stocks…"):
            try:
                if extra_symbols or limited_portfolio_mode:
                    # The scheduled scan contains only the official Nifty 100. Run live
                    # for personal symbols and price-ceiling mode so the live filters apply.
                    price_ceiling = LIMITED_MODE_PRICE_CEILING if limited_portfolio_mode else None
                    scan_payload = scan_nifty100_cached(extra_symbols, max_price=price_ceiling)
                else:
                    try:
                        scheduled = download_scheduled_nifty100_scan()
                    except Exception:
                        scheduled = None
                    has_current_schema = bool(scheduled) and all(
                        "Universe" in row and "Filter status" in row
                        for row in scheduled.get("results", [])
                    )
                    if scheduled and scheduled.get("as_of") == market_date and has_current_schema:
                        scan_payload = scheduled
                    else:
                        if scheduled and market_date and scheduled.get("as_of") != market_date:
                            st.caption("The scheduled leaderboard is from an earlier market close; refreshing the Nifty 100 scan now.")
                        scan_payload = scan_nifty100_cached()
            except Exception as exc:
                scan_payload = {"results": [], "errors": [], "message": str(exc)[:220]}
        all_scan_results = scan_payload.get("results", [])
        if limited_portfolio_mode:
            qualified = [row for row in all_scan_results if row.get("Filter status") == "Pass"]
            qualified.sort(key=lambda row: row.get("Score", -10_000), reverse=True)
            leaders = qualified[:LIMITED_MODE_TOP_N]
            custom_rows = []
            results = leaders
        else:
            leaders = [row for row in all_scan_results if row.get("Universe") != "Added"][:10]
            leader_symbols = {row["Symbol"] for row in leaders}
            custom_rows = [row for row in all_scan_results if row.get("Universe") == "Added" and row["Symbol"] not in leader_symbols]
            results = leaders + custom_rows
        errors = scan_payload.get("errors", [])
        if scan_payload.get("compatibility_notice"):
            st.caption(scan_payload["compatibility_notice"])
    else:
        watchlist = dict(WATCHLIST)
        for raw_symbol in added_symbols.split(","):
            symbol = raw_symbol.strip().upper()
            if symbol:
                watchlist.setdefault(symbol, symbol)

        results, errors = [], []
        with st.spinner("Loading daily prices and calculating indicators…"):
            for symbol, company in watchlist.items():
                try:
                    results.append(evaluate(symbol, company, max_pe, min_sharpe, float(max_drawdown_pct), signal_mode, market["name"]))
                except Exception as exc:
                    errors.append({"Symbol": symbol, "Company": company, "Error": str(exc)[:180]})

    if full_list_view and leaderboard_mode:
        all_eligible = [row for row in scan_payload.get("results", []) if row.get("Filter status") == "Pass"]
        all_eligible.sort(key=lambda row: row.get("Score", -10_000), reverse=True)
        st.subheader("All stocks passing the limited-mode filters" if limited_portfolio_mode else "All stocks passing the filters")
        limited_price_note = f" Each stock is below ₹{LIMITED_MODE_PRICE_CEILING:,.0f}." if limited_portfolio_mode else ""
        st.caption(
            f"{len(all_eligible)} stocks · As of {scan_payload.get('as_of', 'unknown')}. "
            "Entry prices below use the latest closing price as a reference; the next session's actual opening price is not known yet."
            + limited_price_note
        )
        if all_eligible:
            all_display = pd.DataFrame({
                "Stock": [f"{row['Company']} ({row['Symbol']})" for row in all_eligible],
                "Entry price*": [money(row["Price"]) for row in all_eligible],
                "Score rating": [f"{row['Rating']} ({row['Score']:+d}/100)" for row in all_eligible],
            })
            st.dataframe(all_display, hide_index=True, width="stretch", height=min(760, 46 + 44 * len(all_display)))
            st.caption("* Provisional close reference only; re-check against the actual market open before considering an entry. No orders are placed.")
        else:
            st.info(scan_payload.get("message") or "No stocks currently pass the Nifty alignment, SMA 200, and RSI filters.")
        if errors:
            with st.expander(f"Data issues ({len(errors)} symbols)"):
                st.dataframe(pd.DataFrame(errors), hide_index=True, width="stretch")
        return

    def render_screener():
        if not results:
            if leaderboard_mode:
                default_message = (
                    f"No stocks below ₹{LIMITED_MODE_PRICE_CEILING:,.0f} passed the current filters."
                    if limited_portfolio_mode
                    else "No Nifty 100 stocks passed the alignment, RSI, and 200-day SMA filters today. Add a symbol in the sidebar to include it in this table."
                )
                st.info(scan_payload.get("message") or default_message)
                if scan_payload.get("as_of"):
                    st.caption(f"Background or live scan date: {scan_payload['as_of']} · Nifty 100 constituents: {scan_payload.get('constituents', '—')}.")
            else:
                st.error("No symbols could be scanned. Check your internet connection or try again later.")
            if errors:
                st.dataframe(pd.DataFrame(errors), hide_index=True, width="stretch")
            return

        if not leaderboard_mode:
            update_paper_positions(results, signal_mode)
        frame = pd.DataFrame(results)
        buys = int((frame["Action"] == "BUY").sum())
        exits = int(frame["Action"].str.startswith("SELL").sum())
        holds = int((frame["Action"] == "HOLD").sum())
        no_action = len(frame) - buys - exits - holds
        if leaderboard_mode:
            metric_cols = st.columns(3)
            metric_cols[0].metric("Stocks passing filters", scan_payload.get("eligible_count", len(results)))
            metric_cols[1].metric("Top 3 shown" if limited_portfolio_mode else "Top 10 leaders", len(leaders))
            metric_cols[2].metric("Nifty 50 alignment", scan_payload.get("market_regime", market["name"]))
            if limited_portfolio_mode:
                st.subheader("Limited Portfolio Growth · Top 3")
                st.caption(
                    f"As of {scan_payload.get('as_of', 'unknown')}. Up to three highest-scoring stocks pass the Nifty 50 Bull, "
                    f"stock-above-SMA-200, RSI 40–70, and close-below-₹{LIMITED_MODE_PRICE_CEILING:,.0f} filters. "
                    f"The estimated budget is {money(per_stock_budget)} per stock. Share counts and cash required use the latest close; "
                    "the next open can change the actual cost. No orders are placed."
                )
                display = frame[["Company", "Symbol", "Action", "Rating", "Score", "Price", "Entry plan", "Stop loss", "Target"]].copy()
                display.insert(0, "Rank", range(1, len(display) + 1))
                display.rename(columns={"Price": "Close ref", "Entry plan": "Next-open entry", "Stop loss": "2×ATR stop*", "Target": "Final target*"}, inplace=True)
                raw_close_refs = {}
                for symbol in display["Symbol"]:
                    try:
                        raw_history = download_history(symbol, auto_adjust=False)
                        raw_close_refs[symbol] = float(raw_history["Close"].iloc[-1])
                    except Exception:
                        raw_close_refs[symbol] = None
                display["Close ref"] = display["Symbol"].map(raw_close_refs)
                display["Shares to Buy"] = display["Close ref"].map(lambda price: math.floor(per_stock_budget / float(price)) if pd.notna(price) and float(price) > 0 else "—")
                display["Cash Required*"] = [
                    money(int(shares) * float(price)) if shares != "—" and pd.notna(price) else "Unavailable"
                    for shares, price in zip(display["Shares to Buy"], display["Close ref"])
                ]
                display.rename(columns={"Cash Required*": "Cash Required"}, inplace=True)
                display = display[["Rank", "Company", "Symbol", "Action", "Rating", "Score", "Close ref", "Next-open entry", "Shares to Buy", "Cash Required", "2×ATR stop*", "Final target*"]]
            else:
                st.subheader("Nifty 100 · Top 10 by Directional Score")
                st.caption(
                    f"As of {scan_payload.get('as_of', 'unknown')}. Candidates pass the Nifty 50 Bull-regime, stock-above-SMA-200, "
                    "and RSI 40–70 filters. Symbols entered in the sidebar are appended below the leaders and show whether they pass those filters. "
                    "The next session's opening price is unknown until the market opens; starred levels are provisional from the latest close."
                )
                display = frame[["Company", "Symbol", "Universe", "Filter status", "Action", "Rating", "Score", "RSI (14)", "Price", "Entry plan", "Stop loss", "Scale-out level", "Target"]].copy()
                display.insert(0, "Rank", [str(i) if row.get("Universe") != "Added" else "Added" for i, row in enumerate(results, start=1)])
                display.rename(columns={"Universe": "List", "Price": "Close ref", "Stop loss": "2×ATR stop*", "Scale-out level": "Sell 50%*", "Target": "Final target*"}, inplace=True)
            display["Score"] = display["Score"].map(lambda value: f"{value:+d}/100")
            if "RSI (14)" in display:
                display["RSI (14)"] = display["RSI (14)"].map(lambda value: f"{value:.1f}")
            money_columns = ["Close ref", "2×ATR stop*", "Final target*"]
            if not limited_portfolio_mode:
                money_columns.append("Sell 50%*")
            for column in money_columns:
                display[column] = display[column].map(money)
            st.dataframe(display, hide_index=True, width="stretch", height=min(520, 46 + 42 * len(display)))
            if limited_portfolio_mode:
                st.caption("Shares to Buy = floor(per-stock budget ÷ latest close); Cash Required = whole shares × latest close. These are close-based estimates, so recalculate at the actual open. No orders are placed.")
            else:
                st.caption("* Stop, half-off, and target prices use the latest close as a planning reference. They re-anchor to the actual next-open fill; no orders are placed.")
        else:
            metric_cols = st.columns(4)
            for col, label, value in zip(metric_cols, ("BUY setups", "HOLD", "SELL review", "NO ACTION"), (buys, holds, exits, no_action)):
                col.metric(label, value)

            st.subheader("Market scan")
            st.caption("One clear row per stock. The rating and score summarize indicator evidence. Stop/target are anchored for active paper positions; otherwise they are illustrative.")
            display = frame[["Company", "Symbol", "Date", "Action", "Rating", "Score", "Price", "Stop loss", "Target", "Reward/Risk", "Risk %", "Reward %"]].copy()
            display["Score"] = display["Score"].map(lambda value: f"{value:+d}")
            display["Price"] = display["Price"].map(money)
            for column in ("Stop loss", "Target"):
                display[column] = display[column].map(money)
            for column in ("Risk %", "Reward %"):
                display[column] = display[column].map(lambda value: "—" if pd.isna(value) else f"{value:.1f}%")
            display["Reward/Risk"] = display["Reward/Risk"].map(lambda value: "—" if pd.isna(value) else f"{value:.1f}:1")
            st.dataframe(display, hide_index=True, width="stretch", height=min(560, 42 + 40 * len(display)))

        choice_labels = {f"{row['Company']} · {row['Symbol']}": row["Symbol"] for row in results}
        chosen = st.selectbox("Stock details", list(choice_labels), label_visibility="collapsed")
        selected = frame.loc[frame["Symbol"] == choice_labels[chosen]].iloc[0]
        selected_history = add_indicators(download_history(selected["Symbol"]))
        left, right = st.columns([1, 1.4], gap="large")
        with left:
            st.subheader(f"{selected['Company']} · {selected['Symbol']}")
            st.metric("Leaderboard status" if leaderboard_mode else ("Flexible score action" if signal_mode == "Flexible score" else "Strict rules action"), selected["Action"])
            score_cols = st.columns(2)
            score_cols[0].metric("Score rating", selected["Rating"])
            score_cols[1].metric("Directional score", f"{selected['Score']:+d}/100")
            st.write(f"**Latest daily candle:** {selected['Date']} · **Close:** {money(selected['Price'])}")
            st.write(f"**Current market regime:** {selected['Market regime']}")
            st.write(f"**Why:** {selected['Reason']}")
            st.write(f"**Scanner:** {selected['Paper status']}" if leaderboard_mode else f"**Paper tracking:** {selected['Paper status']}")
            if leaderboard_mode:
                if limited_portfolio_mode:
                    st.info(
                        f"Next-open entry: TBD. Latest close reference: {money(selected['Price'])}. "
                        "One provisional 2×ATR stop and one final target are shown; re-anchor both to the actual opening price."
                    )
                    plan_cols = st.columns(2)
                    plan_cols[0].metric("Provisional 2×ATR hard stop", money(selected["Stop loss"]))
                    plan_cols[1].metric("Provisional final target", money(selected["Target"]))
                else:
                    st.info(
                        f"Next-open entry: not known until the market opens. Latest close reference: {money(selected['Price'])}. "
                        "The following levels are provisional and will need to be recalculated from the actual opening fill."
                    )
                    st.metric("Provisional 2×ATR stop", money(selected["Stop loss"]))
                    st.metric("Provisional sell-50% level", money(selected["Scale-out level"]))
                    st.metric("Provisional final target", money(selected["Target"]))
            elif selected["Paper status"].startswith("Active") or selected["Paper status"].startswith("Exit queued"):
                st.write(f"**Paper entry:** {money(selected['Paper entry'])} · **Current stop:** {money(selected['Stop loss'])} · **Fixed target:** {money(selected['Target'])}")
                position = st.session_state.get("paper_positions", {}).get(selected["Symbol"], {})
                if position.get("management_version", 4) >= 5:
                    scale_price = position.get("scale_out_trigger")
                    if position.get("scale_out_done"):
                        st.success(
                            f"Paper rule: 50% was sold at {money(position.get('scale_out_price'))}; "
                            f"the remaining stop is at entry ({money(position['entry_price'])}) and the final target is {money(position['target'])}."
                        )
                    else:
                        st.info(
                            f"Paper rule: when price reaches {money(scale_price)} (+{position['scale_out_atr_multiple']:.1f}× ATR), "
                            f"sell 50% and move the remaining stop to entry ({money(position['entry_price'])}). "
                            f"The final target is {money(position['target'])}."
                        )
                    if position.get("pending_exit"):
                        st.warning(f"Paper exit queued for the next open: {position.get('pending_exit_reason', 'exit pending')}.")
                    else:
                        st.caption(f"Time stop: if still open after session {position.get('sessions_held', 0)}/12 closes, exit at the next session open.")
                elif position.get("breakeven_active"):
                    st.caption(
                        f"{position['market_regime']} regime at entry: stop moved to breakeven after "
                        f"a {position['breakeven_trigger_atr']:.1f} × ATR favorable move; target is "
                        f"{position['target_atr_multiple']:.1f} × ATR from entry."
                    )
                else:
                    st.caption(
                        f"{position['market_regime']} regime at entry: initial 2 × ATR stop and "
                        f"{position['target_atr_multiple']:.1f} × ATR target are fixed; breakeven triggers after "
                        f"a {position['breakeven_trigger_atr']:.1f} × ATR favorable move."
                    )
            elif selected["Paper status"].startswith("Entry queued"):
                position = st.session_state.get("paper_positions", {}).get(selected["Symbol"], {})
                st.caption(
                    f"A paper entry is queued for the next open using {position.get('market_regime', 'current')} regime settings: "
                    f"2 × ATR initial stop, {position.get('target_atr_multiple', selected['Target ATR multiple']):.1f} × ATR target, "
                    f"sell 50% at +{position.get('scale_out_atr_multiple', selected['Scale-out ATR multiple']):.1f} × ATR, "
                    "then move the remaining stop to entry."
                )
            elif selected["Action"] == "BUY":
                st.write(f"**Illustrative stop loss:** {money(selected['Stop loss'])}  ")
                st.write(f"**Illustrative target:** {money(selected['Target'])}")
                st.caption(
                    f"{selected['Market regime']} regime illustration: 2 × ATR stop; sell half at +{selected['Scale-out ATR multiple']:.1f} × ATR, "
                    f"move the remaining stop to entry, then target +{selected['Target ATR multiple']:.1f} × ATR. "
                    "These levels will be recalculated from an actual entry; gaps and costs can change outcomes."
                )
            elif selected["Action"] == "SELL":
                st.write(f"**Illustrative short stop loss:** {money(selected['Stop loss'])}  ")
                st.write(f"**Illustrative short target:** {money(selected['Target'])}")
                st.caption(
                    f"Hypothetical short illustration under {selected['Market regime']} regime: 2 × ATR stop and "
                    f"{selected['Target ATR multiple']:.1f} × ATR target. A SELL flag is not an instruction to open a short position."
                )
            else:
                st.write(f"**Illustrative {selected['Scenario'].lower()} stop loss:** {money(selected['Stop loss'])}  ")
                st.write(f"**Illustrative {selected['Scenario'].lower()} target:** {money(selected['Target'])}")
                st.caption("These are ATR-based scenario levels for comparison; HOLD / NO ACTION does not mean you should enter a position.")

            st.subheader("Your position")
            owns_stock = st.selectbox(
                "Do you currently own this stock?",
                ("Choose one", "Yes", "No"),
                key=f"owns_{selected['Symbol']}",
                help="Answer for your real account. The dashboard does not read or change your brokerage holdings.",
            )
            if owns_stock == "Yes":
                st.caption("Use your actual average entry price and the date you entered. The dashboard only calculates guidance; it cannot see or manage your broker position.")
                already_scaled = False
                if not limited_portfolio_mode:
                    already_scaled = st.checkbox(
                        "I already sold half of this holding",
                        value=False,
                        key=f"scaled_{selected['Symbol']}",
                    )
                earliest_entry = pd.Timestamp(selected_history.index[min(ATR_PERIOD, len(selected_history) - 1)]).date()
                latest_entry = pd.Timestamp(selected_history.index[-1]).date()
                entry_date = st.date_input(
                    "Date you entered",
                    value=latest_entry,
                    min_value=earliest_entry,
                    max_value=latest_entry,
                    key=f"holding_date_{selected['Symbol']}",
                )
                average_entry = st.number_input(
                    "Your average entry price (₹)",
                    min_value=0.01,
                    value=max(float(selected["Price"]), 0.01),
                    step=1.0,
                    key=f"holding_entry_{selected['Symbol']}",
                )
                prior_stock_bars = selected_history.loc[selected_history.index < pd.Timestamp(entry_date)]
                if prior_stock_bars.empty or pd.isna(prior_stock_bars.iloc[-1]["ATR"]):
                    st.warning("There is not enough price history before that entry date to estimate ATR-based management levels.")
                else:
                    entry_atr = float(prior_stock_bars.iloc[-1]["ATR"])
                    signal_date = pd.Timestamp(prior_stock_bars.index[-1])
                    try:
                        nifty = download_nifty_close()
                        nifty_sma200 = nifty.rolling(200, min_periods=200).mean()
                        eligible_nifty = nifty.loc[nifty.index <= signal_date]
                    except Exception:
                        eligible_nifty = pd.Series(dtype=float)
                        nifty_sma200 = pd.Series(dtype=float)
                    if eligible_nifty.empty:
                        ownership_regime = "Unavailable"
                    else:
                        regime_date = eligible_nifty.index[-1]
                        regime_sma = nifty_sma200.loc[regime_date]
                        ownership_regime = (
                            "Unavailable" if pd.isna(regime_sma)
                            else "Bull" if eligible_nifty.iloc[-1] > regime_sma
                            else "Defensive"
                        )
                    if ownership_regime == "Unavailable":
                        st.warning("Nifty regime history is unavailable for that entry date, so the management levels cannot be selected reliably.")
                    else:
                        target_multiple, scale_multiple = market_risk_parameters(ownership_regime)
                        holding_stop = average_entry - ATR_STOP_MULTIPLE * entry_atr
                        holding_target = average_entry + target_multiple * entry_atr
                        current_price = float(selected["Price"])
                        st.write(f"**Entry-date regime:** {ownership_regime} · **ATR used:** {money(entry_atr)} from {signal_date.strftime('%d %b %Y')}")
                        if limited_portfolio_mode:
                            sessions_held = int(((selected_history.index >= pd.Timestamp(entry_date)) & (selected_history.index <= selected_history.index[-1])).sum())
                            st.metric("2×ATR hard stop", money(holding_stop))
                            st.metric("Final target", money(holding_target))
                            st.caption(f"Holding age: {sessions_held}/{PAPER_TIME_STOP_SESSIONS} trading sessions, counting the entry session.")
                            if current_price <= holding_stop:
                                st.error("The estimated hard stop has been reached or crossed. Review the exit under your plan.")
                            elif current_price >= holding_target:
                                st.success("The estimated final target has been reached. Review the planned exit.")
                            elif sessions_held >= PAPER_TIME_STOP_SESSIONS:
                                st.error("TIME STOP REACHED — the position has reached 12 sessions. The rule calls for an exit at the next market open; the dashboard does not place orders.")
                            elif sessions_held == PAPER_TIME_STOP_SESSIONS - 1:
                                st.error("CAPITAL TRAPPED — Day 11 of 12. If the position remains open through the next session close, the time stop calls for an exit at the following market open.")
                            else:
                                st.info("No stop, target, or time-stop level has been reached. Recheck the plan at each daily close.")
                            st.caption("The time-stop count uses available daily candles from the entry date. Stop and target are estimates from pre-entry ATR and exclude costs, taxes, and gaps.")
                        else:
                            scale_price = average_entry + scale_multiple * entry_atr
                            active_stop = average_entry if already_scaled else holding_stop
                            st.metric("Current plan stop", money(active_stop))
                            st.metric("Sell 50% level", "Already done" if already_scaled else money(scale_price))
                            st.metric("Final target", money(holding_target))
                            if current_price <= active_stop:
                                st.error("The estimated stop level has been reached or crossed. Under this plan, exit the remaining holding.")
                            elif current_price >= holding_target:
                                st.success("The estimated final target has been reached. Under this plan, sell the remaining shares.")
                            elif already_scaled:
                                st.info(f"You marked the first half as sold. Keep the stop on the remaining shares at your entry price ({money(average_entry)}) and target {money(holding_target)}.")
                            elif current_price >= scale_price:
                                st.success(f"The estimated half-off level has been reached: the rule says sell 50%, then move the stop on the remaining shares to your entry price ({money(average_entry)}).")
                            else:
                                st.info(f"No management level has been reached yet. Hold to the plan; sell half at {money(scale_price)}, move the remaining stop to {money(average_entry)}, and target {money(holding_target)}.")
                            st.caption("Estimated from the last available ATR and Nifty regime before your entry date; this does not include fees, taxes, dividends, gaps, or any partial sale you may already have made.")
            elif owns_stock == "No":
                if limited_portfolio_mode:
                    st.write("You marked that you do not own this stock. The displayed plan is a single-entry, single-target reference; no order is placed.")
                elif selected["Action"] == "BUY":
                    st.info(f"This is a new-entry setup, not a half-off instruction. If you choose to enter, the current illustration says sell 50% near {money(selected['Price'] + selected['Scale-out ATR multiple'] * selected['ATR (14)'])} and move the remaining stop to entry.")
                else:
                    st.write("You marked that you do not own this stock. There is no holding to scale out of; use the BUY/SELL rating as a research signal only.")
            metric_columns = st.columns(3)
            metric_columns[0].metric("ADX (14)", f"{selected['ADX (14)']:.1f}")
            metric_columns[1].metric("CMF (20)", f"{selected['CMF (20)']:.2f}")
            metric_columns[2].metric("P/E", "N/A" if pd.isna(selected["P/E"]) else f"{selected['P/E']:.1f}×")
            risk_columns = st.columns(3)
            risk_columns[0].metric("1Y stock Sharpe", "N/A" if pd.isna(selected["Sharpe 1Y"]) else f"{selected['Sharpe 1Y']:.2f}")
            risk_columns[1].metric("1Y stock max drawdown", "N/A" if pd.isna(selected["Max DD 1Y %"]) else f"{selected['Max DD 1Y %']:.1f}%")
            risk_columns[2].metric("Bollinger %B", f"{selected['BB %B']:.2f}")
            st.caption(f"RSI: {selected['RSI (14)']:.1f} · Volume: {selected['Volume vs avg']:.2f}× 20-day average · ATR: {money(selected['ATR (14)'])}")
        with right:
            chart = selected_history.tail(500)
            st.subheader("Daily candlestick chart")
            st.caption("Hover for open, high, low, close, and volume. Use the range buttons or drag to zoom.")
            overlay_columns = st.columns(4)
            show_sma20 = overlay_columns[0].checkbox("SMA 20", value=True)
            show_sma50 = overlay_columns[1].checkbox("SMA 50", value=True)
            show_sma200 = overlay_columns[2].checkbox("SMA 200", value=False)
            show_bollinger = overlay_columns[3].checkbox("Bollinger", value=False)
            chart_figure = make_candlestick_chart(chart, show_sma20, show_sma50, show_sma200, show_bollinger)
            st.plotly_chart(chart_figure, width="stretch", config={"displaylogo": False})

        if limited_portfolio_mode:
            with st.expander("Limited Portfolio Growth rules"):
                st.markdown(
                    f"The dashboard shows up to {LIMITED_MODE_TOP_N} highest-scoring Nifty 100 stocks that pass the Nifty 50 Bull-regime, "
                    f"stock-above-SMA-200, RSI 40–70, and close-below-₹{LIMITED_MODE_PRICE_CEILING:,.0f} filters. "
                    "The plan has one next-open entry reference, a fixed 2×ATR stop, and one final target: 4×ATR in Bull regime or 3×ATR in Defensive regime. "
                    f"It estimates whole shares from the per-stock budget of {money(per_stock_budget)} and the latest close; it does not allocate your total account balance or place orders. "
                    f"In **Your position**, the {PAPER_TIME_STOP_SESSIONS}-session count includes the entry session; Day 11 shows a red CAPITAL TRAPPED warning, "
                    "and after the 12th session close the time-stop rule calls for an exit at the next market open. "
                    "All displayed entry and risk prices are provisional references from daily data; actual fills, fees, taxes, and gaps can differ."
                )
            if errors:
                with st.expander(f"Data issues ({len(errors)} symbols)"):
                    st.dataframe(pd.DataFrame(errors), hide_index=True, width="stretch")
            st.caption(f"Last dashboard refresh: {datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')} · For research and education; no trades are placed.")
            return

        with st.expander("Paper trade log"):
            active_positions = st.session_state.get("paper_positions", {})
            active_rows = []
            for symbol, position in active_positions.items():
                if position["status"] == "active":
                    active_rows.append({
                        "Symbol": symbol,
                        "Mode": position["mode"],
                        "Regime at entry": position["market_regime"],
                        "Entry date": position["entry_date"].strftime("%d %b %Y"),
                        "Entry": money(position["entry_price"]),
                        "Stop": money(position["stop"]),
                        "Target": money(position["target"]),
                        "Target ATR": f"{position['target_atr_multiple']:.1f}×",
                        "Management": (
                            f"50% sold at {money(position.get('scale_out_price'))}; stop at entry"
                            if position.get("management_version", 4) >= 5 and position.get("scale_out_done")
                            else f"Sell 50% at +{position.get('scale_out_atr_multiple', 0):.1f}× ATR; then stop at entry"
                            if position.get("management_version", 4) >= 5
                            else f"Legacy breakeven trigger {position['breakeven_trigger_atr']:.1f}× ATR"
                        ),
                        "Sessions": f"{position.get('sessions_held', 0)}/12",
                        "Status": position.get("pending_exit_reason", "Open") if position.get("pending_exit") else "Open",
                    })
                elif position["status"] == "pending":
                    active_rows.append({
                        "Symbol": symbol,
                        "Mode": position["mode"],
                        "Regime at entry": position["market_regime"],
                        "Entry date": position["signal_date"].strftime("%d %b %Y"),
                        "Entry": "Next session open",
                        "Stop": "Set at entry",
                        "Target": "Set at entry",
                        "Target ATR": f"{position['target_atr_multiple']:.1f}×",
                        "Management": f"Sell 50% at +{position.get('scale_out_atr_multiple', 0):.1f}× ATR; then stop at entry",
                        "Sessions": "0/12",
                        "Status": "Entry queued",
                    })
            if active_rows:
                st.dataframe(pd.DataFrame(active_rows), hide_index=True, width="stretch")
            else:
                st.write("No open paper positions in this browser session.")
            closed_rows = st.session_state.get("paper_trades", [])[-10:]
            if closed_rows:
                st.caption("Most recent closed paper positions")
                closed_display = pd.DataFrame(closed_rows).copy()
                closed_display["Entry"] = closed_display["Entry"].map(money)
                closed_display["Exit"] = closed_display["Exit"].map(money)
                if "Scale-out price" not in closed_display:
                    closed_display["Scale-out price"] = None
                closed_display["Scale-out price"] = closed_display["Scale-out price"].map(money)
                closed_display["Return %"] = closed_display["Return %"].map(lambda value: f"{value:+.1f}%")
                closed_display["Result R"] = closed_display["Result R"].map(lambda value: f"{value:+.2f}R")
                st.dataframe(closed_display, hide_index=True, width="stretch")
            st.caption("Paper entries use the next daily open and lock the signal-day ATR and Nifty regime. This log is private to this browser session, is not connected to a broker, and may clear when the app session restarts.")

        with st.expander("How the actions and risk levels are calculated"):
            st.markdown(
                "**Nifty 100 leaderboard:** The main mode uses the current NSE Nifty 100 roster, removes candidates unless Nifty 50 is above its 200-day SMA, the stock is above its own SMA 200, and RSI is 40–70, then sorts by Directional Score. The score uses the same technical and available valuation/history factors as Flexible score. Entry is next open (unknown until then); displayed risk levels use today's close as a reference. Change `SCAN_UNIVERSE` to `WATCHLIST` to restore the previous 10-stock scanner.\n\n"
                "**Flexible score:** Indicator evidence is combined into a directional score from −100 to +100. +55 and above = Strong Buy; +20 to +54 = Buy; −19 to +19 = Hold; −20 to −54 = Sell; −55 and below = Strong Sell. A BUY action starts at score ≥+20; SELL starts at −20. RSI from 50–70 contributes bullish points, with RSI above 70 receiving a smaller boost through 75, or 80 when ADX >25. Ratings are weighted summaries, not probabilities. Missing optional P/E, Sharpe, or drawdown values are omitted and remaining weights are rescaled.\n\n"
                f"The score weighs price/SMA20, SMA20/SMA50, and SMA50/SMA200 (10 points each); MACD (12); RSI (10); high-volume candle, ADX, CMF, and Bollinger position (8 each); 1Y Sharpe and maximum drawdown (6 each); and available P/E (4).\n\n"
                f"**BUY entry gate:** Both signal modes require a weighted score of at least +20 and RSI strictly between 40 and 70. RSI does not need to cross 50 on the signal candle.\n\n"
                f"**Strict rules:** Also requires Close > SMA20 > SMA50 > SMA200, MACD > signal, volume ≥1.2× its 20-day average, ADX ≥{ADX_MINIMUM:.0f}, positive CMF, Bollinger %B ≤1.10, and the selected Sharpe/drawdown/P/E filters to pass.\n\n"
                f"**Market regime:** Nifty 50 above its 200-day SMA selects Bull mode (sell 50% at +2 × ATR, move the remaining stop to entry, and keep a +4 × ATR final target). At or below its 200-day SMA selects Defensive mode (sell 50% at +1.5 × ATR, move the remaining stop to entry, and keep a +3 × ATR final target). If index data is unavailable, BUY setups are paused.\n\n"
                "**Paper trade management:** A BUY queues a virtual entry at the next daily open. At entry, the initial stop is fixed at entry − 2 × the signal day's ATR. The regime-specific 50% scale-out and final target are locked from the signal-day Nifty regime; after scale-out, the remaining stop moves to entry. If the trade is still open at the close of session 12, an exit is queued for the next session open. If stop and target are both touched in one daily candle, the stop is assumed first; gaps through a stop are filled at the open. A SELL signal also queues an exit for the next session open. This is a session-only paper log, not a brokerage position or an order.\n\n"
                "**Your position:** Select whether you own the chosen stock. For an existing holding, enter your average price and entry date; the dashboard estimates the initial stop, 50% scale-out level, and target from ATR before the entry date and the Nifty regime then. It checks the latest close against those levels. It does not know about any partial sales you have already made and cannot access or place orders in your broker account.\n\n"
                "In Strict rules mode, BUY requires both the common score/RSI entry gate and all strict indicator checks. **HOLD** means long-term trend and momentum are positive but one or more BUY checks fail. **SELL** is a review flag; in score mode it reflects a bearish indicator balance, while in strict mode it requires price < SMA50, MACD < signal, ADX ≥20, and CMF <0. Insufficient required data is reported as an error. The displayed 1Y Sharpe and drawdown are historical stock statistics, not a strategy backtest."
            )
            st.write("Indicators: SMA 20/50/200, Wilder RSI(14), MACD(12, 26, 9), ATR(14), Bollinger Bands(20, 2), ADX(14), CMF(20), 20-day average volume, trailing P/E, and one-year historical stock Sharpe/max drawdown.")

        if errors:
            with st.expander(f"Data issues ({len(errors)} symbols)"):
                st.dataframe(pd.DataFrame(errors), hide_index=True, width="stretch")
        st.caption(f"Last dashboard refresh: {datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')} · For research and education; no trades are placed.")

    screener_tab, portfolio_tab = st.tabs(["Screener", "Active Portfolio"])
    with screener_tab:
        render_screener()
    with portfolio_tab:
        render_active_portfolio()

if __name__ == "__main__":
    main()
