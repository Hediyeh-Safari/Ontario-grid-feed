# Ontario Grid Feed

🔗 **Live dashboard:** https://hediyeh-safari.github.io/Ontario-grid-feed/

Daily electricity data for Ontario from IESO public reports, refreshed automatically by a scheduled GitHub Actions job and published with GitHub Pages.

**What the dashboard shows**
- **Power flow:** the sources supplying Ontario's power in any selected hour.
- **Market vs Ontario demand:** the hourly gap between the two demand series (definition to be confirmed with IESO).
- **Duck curve:** net load (demand minus wind and solar) and its largest hourly rise.
- **Generation mix:** daily share of each fuel, plus a 3D view of demand over the last 30 days.

**How it works**
- `scripts/build_feed.py` downloads the latest IESO demand and fuel reports, keeps complete days only, and writes `docs/data/feed.json`.
- `docs/index.html` reads that JSON and draws the charts with Plotly.
- `.github/workflows/daily-feed.yml` runs the script every day and commits the updated data.

**Limitations**
- Only complete days (24 hours of data) are shown.
- Market Demand and Ontario Demand are shown as published; their exact definitions are still being confirmed with IESO.

Built with Python, requests, pandas, and Plotly.
