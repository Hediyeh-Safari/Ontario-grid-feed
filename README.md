# Ontario Grid Feed

🔗 **Live dashboard:** https://hediyeh-safari.github.io/Ontario-grid-feed/

Daily electricity data for Ontario from IESO public reports, updated automatically every day.

- **Power flow:** see where the power comes from in any hour, from nuclear, gas, hydro, wind, solar and more.
- **Duck curve:** net load (demand minus wind and solar) and its largest hourly rise.
- **Generation mix:** daily share of each fuel, with a 3D view of demand over the last 30 days.
- **Automatic updates:** a GitHub Actions job pulls the latest IESO data every day and publishes it to GitHub Pages.

Built with Python, pandas, and Plotly.
