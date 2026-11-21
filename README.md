# StockSignal AI v2
Upload `app.py`, `requirements.txt` and the complete `templates` folder to the root of your GitHub repository.
Render build: `pip install -r requirements.txt`
Render start: `gunicorn app:app`
Render environment: `EODHD_API_TOKEN` (keep secret; do not commit).
Health check: `/health`.
Backtest is illustrative, not investment advice. The model uses adjusted closes for indicators and raw opens/closes for execution. Corporate actions and dividends may affect comparability. Data is EOD, not real time.
