# News Aggregator — Streamlit Edition

Single-process deployment using Streamlit for UI+aggregation.

## Local
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py --server.port 8501
```
Open http://localhost:8501

## Docker (server-ready)
1) Set DNS A-record: `news.yourdomain.com -> <your server IP>`
2) Edit `Caddyfile` and put your domain.
3) Launch:
```bash
docker compose up -d --build
```
Visit: https://news.yourdomain.com (Caddy auto HTTPS).

## Customize
- Change categories/subreddits in `streamlit_app.py`.
- Cache TTL is 300 seconds.
