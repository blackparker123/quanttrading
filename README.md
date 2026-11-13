# QuantTrading

A beginner-friendly Streamlit dashboard for preliminary Indian cash-equity swing research. The main mode scans the current Nifty 100, filters stocks by market alignment, RSI, and their 200-day average, then ranks the top ten by the existing Directional Score. The original ten-stock scanner remains available by changing one code setting. It does not place orders.

## Project structure

```text
QuantTrading/
├── main.py           # Dashboard, downloads, indicators, rules, and risk levels
├── nifty100_engine.py # Nifty 100 constituent download, batch scan, and ranking
├── daily_scan.py     # One-shot runner for the nightly background scan
├── .github/workflows/nifty100-evening-scan.yml # Weekday after-close schedule
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

5. Start the dashboard with computer-only portfolio saving:

   ```powershell
   $env:QUANTTRADING_LOCAL_PORTFOLIO = "1"
   .\.venv\Scripts\python.exe -m streamlit run main.py
   ```

Streamlit opens the dashboard in your browser. The public Streamlit link continues to show the Screener, but its Active Portfolio tab is disabled. The local copy enables Active Portfolio and automatically saves entries in `data/active_portfolio.json` on this computer. In VS Code, stop it with **Ctrl+C** in the terminal.

On macOS/Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, `python -m pip install -r requirements.txt`, and `python -m streamlit run main.py`.

## Main scanner: Nifty 100 leaderboard

The main mode reads the current constituent list from the [official NSE Nifty 100 page](https://www.nseindia.com/static/products-services/indices-nifty100-index), downloads adjusted daily OHLCV in batches, and ranks eligible stocks by the existing Directional Score. A stock is eligible only when Nifty 50 is above its 200-day SMA, the stock closes above its own 200-day SMA, and RSI is between 40 and 70. Standard mode shows up to the ten highest-scoring eligible stocks; the sidebar's **Under ₹2L** setting applies the Limited Portfolio Growth filters and Top 3 cap.

The GitHub Actions workflow runs on weekdays at 16:30 India Standard Time and publishes the latest JSON result on a separate `daily-scan` branch. When that day's scan is not available, the dashboard runs the scan live instead. GitHub-hosted scheduled jobs can start late, and market holidays may produce no new candle; the date shown with the leaderboard identifies the data it used. The workflow can also be started manually from the repository's **Actions** tab.

The next session's opening price is not knowable after today's close. The dashboard therefore labels the entry as **Next open · TBD** and estimates the 2 × ATR stop, 50% scale-out, and final target from today's close. After an actual entry, recalculate those levels from the real opening fill. The app does not submit orders.

To include a stock in the same table, use **Add your own Yahoo Finance symbols** in the left sidebar, enter one or more symbols separated by commas (for example `WIPRO.NS, TATAMOTORS.NS` or `TCS`), and click **Apply symbols**. The app adds those symbols below the Top 10 leaders with a **List = Added** label. It displays them even if they fail the Nifty regime, SMA 200, or RSI filter, and shows the reason in **Filter status**. A ticker that Yahoo Finance cannot load is listed under **Data issues**. Personal additions require a live scan and remain in the open dashboard session; the scheduled scan continues to cover only Nifty 100 constituents.

Use **View all passing stocks** in the top-right corner to open a separate tab with every qualifying stock, its provisional entry-price reference, and its score rating. The list uses each stock's latest close because the next session's opening price is not knowable in advance.

The scoring references are set to P/E 80, preferred 1-year Sharpe 0.5, and preferred maximum drawdown 40%. These factors affect the Directional Score; they are not hard exclusion filters. The explicit eligibility filters remain the Nifty 50 regime, price above SMA 200, and RSI 40–70.

The sidebar **Account Size** radio offers **Standard** and **Under ₹2L**. Standard keeps the Top 10 screen and its existing scale-out plan. Under ₹2L activates **Limited Portfolio Growth**: it runs a live scan, excludes closes of ₹1,000 or more before ranking, and shows at most the three highest-scoring stocks that pass the regular eligibility filters. Its whole-position bracket uses a fixed 2 × ATR stop and one +3 × ATR target in every market regime; there is no trailing stop or partial-exit prompt. Set the per-stock budget in the sidebar (default ₹16,500). For each Top 3 row, **Shares to Buy** is the budget divided by the latest unadjusted close and rounded down to a whole share; **Cash Required** is that quantity times the close. This is an estimate from the previous close, not an order or a guarantee of what the next-open price will cost. Three default budgets total ₹49,500 before brokerage charges, taxes, and other costs. The rupee gain or loss at either bracket level varies with that stock's ATR and price; ₹900 / ₹1,350–₹1,500 are not fixed outcomes.

The dashboard has two tabs: **Screener** and **Active Portfolio**. The public link disables Active Portfolio and never reads or saves holdings. To use it privately, run the local copy with `QUANTTRADING_LOCAL_PORTFOLIO=1` as shown above. After a broker fill, enter the ticker, exact entry price, and entry date. The app fetches daily OHLCV, anchors ATR to the last candle before entry, fixes the stop at entry − 2 × ATR and the final target at entry + 3 × ATR, and counts trading sessions. It gives a color-coded HOLD, TARGET HIT, STOP HIT, or TIME STOP command. There is no trailing stop or scale-out. Adding or editing a row saves automatically to an ignored JSON file inside this project folder; deleting a row removes it from that local file. No CSV or cloud account setup is needed. The local scan runs when the tab is open; use `python portfolio_scan.py` to refresh its saved action snapshot when the app is closed. It does not place or monitor broker orders.

### Roll back to the original scanner

Near the top of `main.py`, change:

```python
SCAN_UNIVERSE = "NIFTY100"
```

to:

```python
SCAN_UNIVERSE = "WATCHLIST"
```

That restores the earlier ten-stock scanner and its custom-symbol input. The code update is also isolated in its own Git commit, so it can be reverted without resetting other project history.

## Original watchlist

The rollback watchlist is the ten largest Nifty 50 constituents by weight according to the May 29, 2026 Nifty Indices factsheet. Index membership and weights change; edit the `WATCHLIST` dictionary near the top of `main.py` when you want a different set. NSE Yahoo Finance symbols use the `.NS` suffix.

In either mode, you can add symbols without changing code using the dashboard's left sidebar. In `WATCHLIST` rollback mode they join the scan. In Nifty 100 mode they appear beneath the Top 10 as described above.

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

- **Flexible score:** Indicator factors add bullish or bearish points to a score from −100 to +100. A score of +55 or more is **Strong Buy**, +20 to +54 is **Buy**, −19 to +19 is **Hold**, −20 to −54 is **Sell**, and −55 or lower is **Strong Sell**. BUY requires score ≥+20 and RSI strictly between 40 and 70; there is no RSI crossover requirement. RSI from 50–70 contributes bullish points, with a smaller boost above 70 through 75 (or 80 when ADX >25). SELL starts at −20; scores are weighted summaries, not probabilities.
- Weights: price vs. SMA 20, SMA 20 vs. SMA 50, and SMA 50 vs. SMA 200 (10 points each); MACD (12); RSI (10); high-volume candle, ADX, CMF, and Bollinger position (8 each); 1Y Sharpe and maximum drawdown (6 each); and available trailing P/E (4 when its filter is enabled). The sidebar Sharpe and drawdown limits affect their score contributions. Missing optional P/E, Sharpe, or drawdown data is omitted and the remaining weights are rescaled.
- RSI contributes bullish points from 50–70, with a smaller boost above 70 through the RSI ceiling (75, or 80 when ADX >25). Bollinger %B up to 1.10 is allowed to accommodate band-riding breakouts; above 1.10 weighs against a BUY.
- **Strict rules:** Requires the same score and RSI BUY entry gate, plus Close > SMA20 > SMA50 > SMA200, MACD above signal, volume ≥1.2× its 20-day average, ADX ≥20, positive CMF, Bollinger %B ≤1.10, and the selected Sharpe, drawdown, and P/E filters to pass. A score rating is still shown as context.

- In Strict rules mode, **HOLD** means long-term trend and momentum are positive and CMF is not strongly negative, but one or more BUY checks fail. **SELL** requires Close < SMA50, MACD below signal, ADX ≥20, and CMF negative. Otherwise, the result is **NO ACTION**. A SELL is a review flag, not an automatic sell order.

The sidebar lets you set a maximum P/E (0 disables the filter), a minimum one-year Sharpe, and a maximum historical drawdown for BUY setups. The summary table shows risk percentage, reward percentage, and reward/risk ratio for every stock, regardless of its action.

The dashboard classifies the market using the latest Nifty 50 close versus its 200-day SMA. Above the SMA is **Bull** mode: sell 50% at +2 × signal-day ATR, move the remaining stop to entry, and keep a +4 × ATR final target. At or below the SMA is **Defensive** mode: sell 50% at +1.5 × ATR, move the remaining stop to entry, and keep a +3 × ATR final target. If Nifty data is unavailable, BUY setups are paused.

When a BUY appears, the dashboard queues a **paper entry** for the next daily open. At entry, it logs the entry price and fixes the initial stop at entry − 2 × signal-day ATR. The 50% scale-out and final target multiples are saved from the signal-day market regime and remain fixed for that position if the market regime later changes. After the half-off level is reached, the remaining stop moves to entry. If a position is still open at the close of its 12th session, the dashboard queues a paper exit for the next session open. A SELL signal also queues a paper exit for the next open. Gap risk applies, and if stop and target both fall inside one daily candle, the simulator assumes the stop was hit first.

The **Your position** panel asks whether you already own the selected stock. For an existing holding, enter your average entry price and entry date to see the estimated stop, 50% scale-out level, final target, and whether the latest close has reached one of those levels. ATR is taken from the last available daily bar before the entered date, and the Nifty regime is selected for that date. If you have already sold half, mark that in the panel so it reports the breakeven stop and remaining target without repeating the half-off instruction. This is an estimate and does not include fees, taxes, dividends, gaps, or broker holdings.

The **Paper trade log** is in-memory for the current browser session only. It is not connected to a broker or an actual portfolio and may clear if the app session restarts. When no paper position is open, displayed levels remain illustrative scenarios based on the latest close. No real trades are placed.

## Data and limitations

The app asks yfinance for two years of daily adjusted OHLCV data, enough history for the 200-day average, and separately downloads Nifty 50 closes for the regime filter. Data is cached for 15 minutes; use **Refresh market data** to clear both caches. A network failure, rate limit, missing symbol, or short history is shown in the dashboard instead of stopping the whole scan. If the Nifty data is unavailable, the stock scan continues but BUY setups are paused.

This is a technical screening example for research and education. The Nifty 100 leaderboard has not yet been backtested or validated as profitable. Earlier strategy simulations used only the ten-stock watchlist and do not validate the expanded universe or predict future results. The dashboard does not consider your financial circumstances and is not personalized financial advice. It only uses holdings details you enter for the selected stock; it cannot verify your portfolio, capital, risk tolerance, or tax situation. Review the chart, data date, and rules yourself; the dashboard never connects to a broker or places trades.

## Strategy revision history

- **Pre-update:** Flexible-score BUY at +20 without an RSI crossover gate; RSI from 50–70 added bullish points, with a smaller boost above 70 through 75 (or 80 when ADX >25).
- **Update 1:** Required RSI to cross up through 50 (RSI ≤65) for BUY; added the session paper-trade log with a fixed 2 × ATR initial stop, 4 × ATR target, and breakeven move at +1.5 × ATR.
- **Update 2:** Restores score-based BUY at +20 and the pre-update RSI weighting/ceilings; keeps the entry-anchored 2 × ATR stop and 4 × ATR target, and moves the breakeven trigger to +2.5 × ATR.
- **Update 3:** Adds a Nifty 50 / SMA 50 regime filter. Bull mode uses a 4 × ATR target and +2.5 × ATR breakeven trigger; Defensive mode uses a 2 × ATR target and +1 × ATR breakeven trigger. The regime-specific multiples are locked at signal time; price levels are anchored to the next-open paper entry.
- **Update 4:** Switches the market filter to Nifty 50 / SMA 200 and requires BUY score ≥+20 with RSI strictly between 40 and 70. Bull mode remains 4 × ATR / +2.5 × ATR; Defensive mode changes to 3 × ATR / +2 × ATR. The initial stop stays fixed at 2 × ATR.
- **Update 5:** Adds a 50% scale-out at +2 × ATR in Bull mode or +1.5 × ATR in Defensive mode; the remaining stop moves to entry, with final targets of +4 × ATR / +3 × ATR. Adds a 12-session time stop that queues exit for the next open, plus an ownership panel that estimates management levels from the user's entered average price and entry date.
- **Update 6:** Makes a Nifty 100 Top 10 leaderboard the main scanner. It filters for Nifty 50 Bull alignment, close above each stock's SMA 200, and RSI 40–70; ranks by the existing Directional Score; and adds a weekday 16:30 IST GitHub Actions scan. Tomorrow's open is shown as TBD, with close-based provisional stop/scale-out/target prices. Set `SCAN_UNIVERSE = "WATCHLIST"` to restore the previous scanner.
- **Update 7:** Adds a sidebar account-size choice. Under ₹2L activates Limited Portfolio Growth: Top 3 eligible stocks with close below ₹1,000, one 2 × ATR stop and one regime-based final target, plus a Day 11 capital-velocity warning and the existing 12-session exit rule. Standard mode preserves the earlier Top 10 and scale-out behavior.
- **Update 8:** Changes the Limited Portfolio Growth plan to a fixed whole-position 2 × ATR stop and 3 × ATR target, with no trailing or partial exits. Adds an editable Active Portfolio ledger with 12-session HOLD/STOP/TARGET/TIME STOP commands, local-only automatic saving to an ignored JSON file; the hosted public link disables portfolio data.
