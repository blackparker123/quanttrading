# QuantTrading

A beginner-friendly Streamlit dashboard for preliminary Indian cash-equity swing research. It scans ten high-weight Nifty 50 constituents, downloads daily adjusted OHLCV data, calculates common trend/momentum/volume indicators, and shows a flexible weighted rating or a stricter rule-based action with an explanation. It does not place orders.

## Project structure

```text
QuantTrading/
├── main.py           # Dashboard, downloads, indicators, rules, and risk levels
├── requirements.txt  # Python packages to install, including Plotly charts
├── README.md         # Setup, usage, and rule explanations
└── .gitignore        # Keeps virtual environments and local secrets out of Git
```

## Open and run in VS Code on Windows

1. In VS Code, choose **File → Open Folder** and open this `QuantTrading` folder.
2. Open **Terminal → New Terminal**.
3. Create a private Python environment in the project folder:

   ```powershell
   py -m venv .venv
   ```

4. Install the packages:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. Start the dashboard:

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run main.py
   ```

Streamlit opens the dashboard in your browser. In VS Code, stop it with **Ctrl+C** in the terminal.

On macOS/Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, `python -m pip install -r requirements.txt`, and `python -m streamlit run main.py`.

## Watchlist

The starter watchlist is the ten largest Nifty 50 constituents by weight according to the May 29, 2026 Nifty Indices factsheet. Index membership and weights change; edit the `WATCHLIST` dictionary near the top of `main.py` when you want a different set. NSE Yahoo Finance symbols use the `.NS` suffix.

You can also add symbols without changing code: in the dashboard's left sidebar, enter comma-separated Yahoo Finance symbols in **Add your own Yahoo Finance symbols**, for example `WIPRO.NS, TATAMOTORS.NS`. They are included in the scan while entered. If Yahoo Finance does not recognize a symbol, that row appears under **Data issues**.

## Indicators and rules

- **SMA 20 / 50 / 200:** Average adjusted daily close over the last 20, 50, or 200 sessions.
- **RSI (14):** Wilder-style relative strength index, a momentum measure from 0 to 100.
- **MACD (12, 26, 9):** Difference between 12- and 26-session exponential averages plus its 9-session signal average.
- **ATR (14):** Average true range, a measure of recent daily price movement.
- **Bollinger Bands (20, 2):** The 20-day average plus/minus two standard deviations. The strict BUY rule permits a breakout through %B 1.10 and blocks a more extended move.
- **ADX (14):** Trend strength; BUY and SELL require ADX of at least 20 so weak, directionless moves do not trigger those labels.
- **CMF (20):** Chaikin Money Flow; BUY requires positive flow and SELL requires negative flow.
- **Candlestick chart:** Daily OHLC candles with volume below; SMA and Bollinger overlays can be switched on/off to keep the chart readable.
- **Volume average (20):** Mean daily volume over 20 sessions; the dashboard also shows the latest volume relative to this average.
- **Trailing P/E:** Retrieved from Yahoo Finance when available. The sidebar's maximum P/E is a configurable BUY filter; set it to `0` to disable it. Missing P/E is shown as N/A and does not block a signal.
- **1Y stock Sharpe and max drawdown:** Calculated from the stock's past year of daily buy-and-hold returns and used as configurable BUY filters. These describe the stock's history, not a portfolio or a backtest of this scanner's strategy.

Choose **Flexible score** or **Strict rules** in the sidebar. Flexible score is the default. The preliminary logic is intentionally visible and editable in `evaluate()` and `weighted_score()` in `main.py`:

- **Flexible score:** Indicator factors add bullish or bearish points to a score from −100 to +100. A score of +55 or more is **Strong Buy**, +20 to +54 is **Buy**, −19 to +19 is **Hold**, −20 to −54 is **Sell**, and −55 or lower is **Strong Sell**. A BUY action starts at score ≥+20, with no RSI crossover gate. RSI from 50–70 contributes bullish points; RSI above 70 gets a smaller boost through 75, or 80 when ADX >25. SELL starts at −20; scores are weighted summaries, not probabilities.
- Weights: price vs. SMA 20, SMA 20 vs. SMA 50, and SMA 50 vs. SMA 200 (10 points each); MACD (12); RSI (10); high-volume candle, ADX, CMF, and Bollinger position (8 each); 1Y Sharpe and maximum drawdown (6 each); and available trailing P/E (4 when its filter is enabled). The sidebar Sharpe and drawdown limits affect their score contributions. Missing optional P/E, Sharpe, or drawdown data is omitted and the remaining weights are rescaled.
- RSI contributes bullish points from 50–70, with a smaller boost above 70 through the RSI ceiling (75, or 80 when ADX >25). Bollinger %B up to 1.10 is allowed to accommodate band-riding breakouts; above 1.10 weighs against a BUY.
- **Strict rules:** Requires Close > SMA20 > SMA50 > SMA200, MACD above signal, RSI between 50 and 75 (up to 80 when ADX >25), volume ≥1.2× its 20-day average, ADX ≥20, positive CMF, Bollinger %B ≤1.10, and the selected Sharpe, drawdown, and P/E filters to pass. RSI need not cross 50 on the signal day. A score rating is still shown as context.

- In Strict rules mode, **HOLD** means long-term trend and momentum are positive and CMF is not strongly negative, but one or more BUY checks fail. **SELL** requires Close < SMA50, MACD below signal, ADX ≥20, and CMF negative. Otherwise, the result is **NO ACTION**. A SELL is a review flag, not an automatic sell order.

The sidebar lets you set a maximum P/E (0 disables the filter), a minimum one-year Sharpe, and a maximum historical drawdown for BUY setups. The summary table shows risk percentage, reward percentage, and reward/risk ratio for every stock, regardless of its action.

The dashboard classifies the market using the latest Nifty 50 close versus its 50-day SMA. Above the SMA is **Bull** mode: target = entry + 4 × signal-day ATR and breakeven trigger = +2.5 × ATR. At or below the SMA is **Defensive** mode: target = entry + 2 × ATR and breakeven trigger = +1 × ATR. If Nifty data is unavailable, BUY setups are paused.

When a BUY appears, the dashboard queues a **paper entry** for the next daily open. At entry, it logs the entry price and fixes the initial stop at entry − 2 × signal-day ATR. Target and breakeven trigger multiples are saved from the signal-day market regime and remain fixed for that position if the market regime later changes. A SELL signal queues a paper exit at the next open. Gap risk applies, and if stop and target both fall inside one daily candle, the simulator assumes the stop was hit first.

The **Paper trade log** is in-memory for the current browser session only. It is not connected to a broker or an actual portfolio and may clear if the app session restarts. When no paper position is open, displayed levels remain illustrative scenarios based on the latest close. No real trades are placed.

## Data and limitations

The app asks yfinance for two years of daily adjusted OHLCV data, enough history for the 200-day average, and separately downloads Nifty 50 closes for the regime filter. Data is cached for 15 minutes; use **Refresh market data** to clear both caches. A network failure, rate limit, missing symbol, or short history is shown in the dashboard instead of stopping the whole scan. If the Nifty data is unavailable, the stock scan continues but BUY setups are paused.

This is a technical screening example for research and education. The current Update 3 settings have not yet been backtested or validated as profitable. Earlier versions had a limited one-year historical simulation; that does not predict future results. The dashboard does not consider your financial circumstances and is not personalized financial advice. It cannot know your holdings, entry price, capital, risk tolerance, or tax situation. Review the chart, data date, and rules yourself; the dashboard never connects to a broker or places trades.

## Strategy revision history

- **Pre-update:** Flexible-score BUY at +20 without an RSI crossover gate; RSI from 50–70 added bullish points, with a smaller boost above 70 through 75 (or 80 when ADX >25).
- **Update 1:** Required RSI to cross up through 50 (RSI ≤65) for BUY; added the session paper-trade log with a fixed 2 × ATR initial stop, 4 × ATR target, and breakeven move at +1.5 × ATR.
- **Update 2:** Restores score-based BUY at +20 and the pre-update RSI weighting/ceilings; keeps the entry-anchored 2 × ATR stop and 4 × ATR target, and moves the breakeven trigger to +2.5 × ATR.
- **Update 3:** Adds a Nifty 50 / SMA 50 regime filter. Bull mode uses a 4 × ATR target and +2.5 × ATR breakeven trigger; Defensive mode uses a 2 × ATR target and +1 × ATR breakeven trigger. The regime-specific multiples are locked at signal time; price levels are anchored to the next-open paper entry.
