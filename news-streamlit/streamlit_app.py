import math
from datetime import datetime, timezone
from dateutil import tz
import httpx
import streamlit as st

st.set_page_config(page_title="Trending News", page_icon="📰", layout="wide")

CATEGORIES = {
    "general": ["news", "worldnews"],
    "technology": ["technology", "programming", "gadgets"],
    "sports": ["sports", "soccer", "nba"],
    "entertainment": ["entertainment", "movies", "television"],
    "business": ["business", "economy", "stocks"],
    "science": ["science"],
}

def time_decay_score(dt):
    if not dt:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds()/3600.0
    return 100.0 * math.exp(-age_hours / 24.0)

def normalize_points(points):
    if not points:
        return 0.0
    return math.log10(max(points, 1)) * 100.0

def parse_dt_iso(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None

def fetch_hn():
    url = "https://hn.algolia.com/api/v1/search?tags=front_page"
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent":"NewsStreamlit/1.0"}) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for h in data.get("hits", []):
        url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        title = h.get("title") or "(no title)"
        points = int(h.get("points") or 0)
        comments = int(h.get("num_comments") or 0)
        author = h.get("author")
        dt = parse_dt_iso(h.get("created_at"))
        out.append({
            "title": title,
            "url": url,
            "source": "Hacker News",
            "points": points,
            "comments": comments,
            "author": author,
            "published_at": dt,
        })
    return out

def fetch_reddit(sub):
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=25"
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent":"NewsStreamlit/1.0 (+https://example.com)"}) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        dt = None
        cu = d.get("created_utc")
        try:
            if cu:
                dt = datetime.fromtimestamp(float(cu), tz=timezone.utc)
        except Exception:
            dt = None
        out.append({
            "title": d.get("title") or "(no title)",
            "url": d.get("url_overridden_by_dest") or d.get("url") or f"https://reddit.com{d.get('permalink','')}",
            "source": f"r/{sub}",
            "points": int(d.get("ups") or d.get("score") or 0),
            "comments": int(d.get("num_comments") or 0),
            "author": d.get("author"),
            "published_at": dt,
        })
    return out

@st.cache_data(ttl=300, show_spinner=False)
def get_trending(category: str):
    subs = CATEGORIES.get(category, CATEGORIES["general"])
    articles = []
    for s in subs:
        articles.extend(fetch_reddit(s))
    articles.extend(fetch_hn())
    for a in articles:
        a["score"] = normalize_points(a.get("points")) + time_decay_score(a.get("published_at"))
        a["category"] = category
    seen = set()
    deduped = []
    for a in articles:
        key = (a["url"], a["title"][:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)
    deduped.sort(key=lambda x: x["score"], reverse=True)
    return deduped

def fmt_time(dt):
    if not dt:
        return "unknown"
    local = dt.astimezone(tz.tzlocal())
    return local.strftime("%Y-%m-%d %H:%M")

st.sidebar.title("Settings")
category = st.sidebar.selectbox("Category", list(CATEGORIES.keys()), index=0)
limit = st.sidebar.slider("Items", 5, 50, 10)
query = st.sidebar.text_input("Search title")
st.sidebar.caption("Data cached for 5 minutes to avoid rate limits.")

st.title("📰 Trending News (Streamlit)")
with st.spinner("Fetching…"):
    items = get_trending(category)[:limit]

if query:
    items = [a for a in items if query.lower() in a["title"].lower()]

for a in items:
    col1, col2 = st.columns([0.82, 0.18])
    with col1:
        st.markdown(f"**[{a['title']}]({a['url']})**")
        st.caption(f"{a['source']} • {a['category']} • {fmt_time(a['published_at'])}")
    with col2:
        st.metric("Score", f"{a['score']:.1f}", help=f"points={a['points']}, comments={a['comments']}")
    st.divider()

st.caption("Sources: Hacker News (Algolia) and Reddit hot posts.")
