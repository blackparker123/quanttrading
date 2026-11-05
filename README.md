# QuantTrading

A beginner-friendly Streamlit dashboard for preliminary Indian cash-equity swing research. It scans ten high-weight Nifty 50 constituents, downloads daily adjusted OHLCV data, calculates common trend/momentum/volume indicators, and shows a rule-based action with an explanation. It does not place orders.

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
- **Bollinger Bands (20, 2):** The 20-day average plus/minus two standard deviations; BUY is blocked if the latest close is above the upper band.
- **ADX (14):** Trend strength; BUY and SELL require ADX of at least 20 so weak, directionless moves do not trigger those labels.
- **CMF (20):** Chaikin Money Flow; BUY requires positive flow and SELL requires negative flow.
- **Candlestick chart:** Daily OHLC candles with volume below; SMA and Bollinger overlays can be switched on/off to keep the chart readable.
- **Volume average (20):** Mean daily volume over 20 sessions; the dashboard also shows the latest volume relative to this average.
- **Trailing P/E:** Retrieved from Yahoo Finance when available. The sidebar's maximum P/E is a configurable BUY filter; set it to `0` to disable it. Missing P/E is shown as N/A and does not block a signal.
- **1Y stock Sharpe and max drawdown:** Calculated from the stock's past year of daily buy-and-hold returns and used as configurable BUY filters. These describe the stock's history, not a portfolio or a backtest of this scanner's strategy.

The preliminary rules are intentionally visible and editable in `evaluate()` in `main.py`:

- **BUY:** Close > SMA20 > SMA50 > SMA200, MACD above signal, RSI 50–70, volume ≥1.2× its 20-day average, ADX ≥20, positive CMF, close no higher than the upper Bollinger Band, and the selected Sharpe, drawdown, and P/E filters pass.
- **HOLD:** Long-term trend and momentum are positive and CMF is not strongly negative, but one or more BUY checks fail.
- **SELL:** Close < SMA50, MACD below signal, ADX ≥20, and CMF negative. This is a review flag, not an automatic sell order.
- **NO ACTION:** The BUY and WATCH conditions are not met.

The sidebar lets you set a maximum P/E (0 disables the filter), a minimum one-year Sharpe, and a maximum historical drawdown for BUY setups. The summary table shows risk percentage, reward percentage, and reward/risk ratio for every stock, regardless of its action.

For BUY, HOLD, and NO ACTION, the table shows an illustrative long-side scenario: stop = latest close − 2 × ATR(14), with the target two times that risk distance above the close. For SELL, it shows a hypothetical short-side scenario: stop = latest close + 2 × ATR(14), with the target two times that risk distance below the close. HOLD / NO ACTION scenarios are for comparison, not entry suggestions; a SELL flag is not an instruction to open a short position. These are not personalized order levels and use the latest close, not your actual entry price. Gaps, costs, and slippage can change outcomes.

## Data and limitations

The app asks yfinance for two years of daily adjusted OHLCV data, enough history for the 200-day average. Data is cached for 15 minutes; use **Refresh market data** to clear the cache. A network failure, rate limit, missing symbol, or short history is shown in the dashboard instead of stopping the whole scan.

This is a technical screening example for research and education. It has not been backtested or validated as a profitable strategy, does not consider fundamentals or your financial circumstances, and is not personalized financial advice. It cannot know your holdings, entry price, capital, risk tolerance, or tax situation. Review the chart, data date, and rules yourself; the dashboard never connects to a broker or places trades.

