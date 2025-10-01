import math
from datetime import datetime, timezone
from dateutil import tz
from typing import List, Dict, Any
import httpx
import streamlit as st
import pandas as pd

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Trending News", page_icon="📰", layout="wide")

# -----------------------------
# Category -> default subreddits
# -----------------------------
DEFAULT_CATEGORIES = {
    "general": ["news", "worldnews"],
    "technology": ["technology", "programming", "gadgets"],
    "sports": ["sports", "soccer", "nba"],
    "entertainment": ["entertainment", "movies", "television"],
    "business": ["business", "economy", "stocks"],
    "science": ["science"],
}

# -----------------------------
# Utilities: scoring, time, etc.
# -----------------------------
def time_decay_score(dt: datetime | None) -> float:
    if not dt:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    # Recent posts get higher score; ~1 day half-life
    return 100.0 * math.exp(-age_hours / 24.0)

def normalize_points(points: int | None) -> float:
    if not points:
        return 0.0
    # Log scaling so giant threads don't completely dominate
    return math.log10(max(points, 1)) * 100.0

def parse_dt_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None

def fmt_time(dt: datetime | None) -> str:
    if not dt:
        return "unknown"
    local = dt.astimezone(tz.tzlocal())
    return local.strftime("%Y-%m-%d %H:%M")

# -----------------------------
# Fetchers (HN + Reddit)
# -----------------------------
HN_URL = "https://hn.algolia.com/api/v1/search?tags=front_page"
REDDIT_TPL = "https://www.reddit.com/r/{sub}/hot.json?limit=25"
HEADERS = {"User-Agent": "NewsStreamlit/2.0 (+https://example.com)"}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_hn() -> List[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS) as client:
            r = client.get(HN_URL)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return [{"__error__": f"HN fetch failed: {e}"}]

    out: List[Dict[str, Any]] = []
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

@st.cache_data(ttl=300, show_spinner=False)
def fetch_reddit(sub: str) -> List[Dict[str, Any]]:
    url = REDDIT_TPL.format(sub=sub)
    try:
        with httpx.Client(timeout=15.0, headers=HEADERS) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return [{"__error__": f"r/{sub} fetch failed: {e}"}]

    out: List[Dict[str, Any]] = []
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

# -----------------------------
# Aggregation with options
# -----------------------------
def aggregate(
    category: str,
    enable_hn: bool,
    enable_reddit: bool,
    subreddits: List[str]
) -> List[Dict[str, Any]]:
    articles: List[Dict[str, Any]] = []

    if enable_reddit:
        for s in subreddits:
            articles.extend(fetch_reddit(s))

    if enable_hn:
        # HN is mostly tech/general but often overlaps other categories
        articles.extend(fetch_hn())

    # Compute composite score & attach category
    for a in articles:
        a["score"] = normalize_points(a.get("points")) + time_decay_score(a.get("published_at"))
        a["category"] = category

    # De-duplicate by (url, title)
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for a in articles:
        key = (a.get("url"), (a.get("title") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    return deduped

# -----------------------------
# Sidebar controls
# -----------------------------
st.sidebar.title("Settings")

# Persist user choices across reloads
if "favorites" not in st.session_state:
    st.session_state["favorites"] = {}

# Category + subreddit selection
category = st.sidebar.selectbox("Category", list(DEFAULT_CATEGORIES.keys()), index=0)
default_subs = DEFAULT_CATEGORIES.get(category, DEFAULT_CATEGORIES["general"])
user_subs = st.sidebar.multiselect("Subreddits for this category", default_subs, default=default_subs)

# Sources toggles
cols_src = st.sidebar.columns(2)
with cols_src[0]:
    enable_hn = st.checkbox("Hacker News", value=True)
with cols_src[1]:
    enable_reddit = st.checkbox("Reddit", value=True)

# Filters
st.sidebar.markdown("### Filters")
search_q = st.sidebar.text_input("Search in title")
include_kw = st.sidebar.text_input("Include keywords (comma-sep)")
exclude_kw = st.sidebar.text_input("Exclude keywords (comma-sep)")

# Sorting + pagination
st.sidebar.markdown("### Sorting & Pagination")
sort_by = st.sidebar.selectbox("Sort by", ["Score (default)", "Points", "Newest"], index=0)
page_size = st.sidebar.slider("Page size", 5, 50, 10)
page = st.sidebar.number_input("Page #", min_value=1, value=1, step=1)

# Auto refresh
auto_refresh = st.sidebar.checkbox("Auto refresh every 60s", value=False)
if auto_refresh:
    st.experimental_rerun  # noop reference to avoid linter warning
    st.runtime.legacy_caching.caching._mem_caches  # no-op to keep importers happy
    st.experimental_set_query_params(refresh=str(datetime.utcnow().timestamp()))
    st.autorefresh(interval=60_000, limit=1000, key="autorefresh")

# -----------------------------
# Main content
# -----------------------------
st.title("📰 Trending News (Streamlit)")

# Fetch & aggregate
with st.spinner("Fetching…"):
    if not (enable_hn or enable_reddit):
        items: List[Dict[str, Any]] = []
    else:
        items = aggregate(category, enable_hn, enable_reddit, user_subs)

# Error surface (if any fetchers returned an error record)
errors = [a["__error__"] for a in items if "__error__" in a]
items = [a for a in items if "__error__" not in a]
if errors:
    with st.expander("⚠️ Some sources had issues (click to expand)"):
        for e in errors:
            st.write("- " + str(e))

# Basic title search
if search_q:
    items = [a for a in items if search_q.lower() in (a.get("title","").lower())]

# Include/exclude keywords
def matches_keywords(text: str, keywords_csv: str, must_include: bool) -> bool:
    if not keywords_csv.strip():
        return True
    kws = [k.strip().lower() for k in keywords_csv.split(",") if k.strip()]
    if not kws:
        return True
    t = text.lower()
    if must_include:
        return any(k in t for k in kws)
    else:
        return not any(k in t for k in kws)

filtered = []
for a in items:
    title = a.get("title", "")
    if not matches_keywords(title, include_kw, must_include=True):
        continue
    if not matches_keywords(title, exclude_kw, must_include=False):
        continue
    filtered.append(a)
items = filtered

# Sort
if sort_by == "Points":
    items.sort(key=lambda x: (x.get("points") or 0), reverse=True)
elif sort_by == "Newest":
    items.sort(key=lambda x: x.get("published_at") or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
else:  # Score
    items.sort(key=lambda x: x.get("score") or 0.0, reverse=True)

total = len(items)
start = (page - 1) * page_size
end = start + page_size
page_items = items[start:end]

st.caption(f"{total} articles • showing {start+1}-{min(end,total)}")

# Export controls
def to_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "title": r.get("title"),
        "url": r.get("url"),
        "source": r.get("source"),
        "category": r.get("category"),
        "points": r.get("points"),
        "comments": r.get("comments"),
        "author": r.get("author"),
        "published_at": r.get("published_at").isoformat() if r.get("published_at") else None,
        "score": round(float(r.get("score") or 0.0), 2),
        "favorite": r.get("url") in st.session_state["favorites"],
    } for r in rows])

exp_cols = st.columns(3)
with exp_cols[0]:
    st.download_button("⬇️ Download CSV (page)", data=to_df(page_items).to_csv(index=False).encode("utf-8"),
                       file_name="news_page.csv", mime="text/csv")
with exp_cols[1]:
    st.download_button("⬇️ Download JSON (page)", data=to_df(page_items).to_json(orient="records"),
                       file_name="news_page.json", mime="application/json")
with exp_cols[2]:
    fav_df = to_df([v for v in st.session_state["favorites"].values()])
    st.download_button("⭐ Export Favorites (CSV)", data=fav_df.to_csv(index=False).encode("utf-8"),
                       file_name="favorites.csv", mime="text/csv", disabled=fav_df.empty)

st.divider()

# Render cards + Favorites
def toggle_favorite(a: Dict[str, Any]):
    key = a.get("url") or a.get("title")
    if key in st.session_state["favorites"]:
        st.session_state["favorites"].pop(key, None)
    else:
        st.session_state["favorites"][key] = a

for a in page_items:
    col1, col2, col3 = st.columns([0.70, 0.15, 0.15])
    with col1:
        st.markdown(f"**[{a['title']}]({a['url']})**")
        st.caption(f"{a['source']} • {a['category']} • {fmt_time(a['published_at'])}")
    with col2:
        st.metric("Score", f"{a['score']:.1f}", help=f"points={a['points']}, comments={a['comments']}")
    with col3:
        fav_key = (a.get("url") or a.get("title"))
        is_fav = fav_key in st.session_state["favorites"]
        label = "★ Unsave" if is_fav else "☆ Save"
        st.button(label, key=f"fav-{fav_key}", on_click=toggle_favorite, args=(a,))
    st.divider()

# Favorites panel
with st.expander(f"⭐ Favorites ({len(st.session_state['favorites'])})"):
    if not st.session_state["favorites"]:
        st.write("No favorites yet. Click **☆ Save** on any card.")
    else:
        for a in st.session_state["favorites"].values():
            st.markdown(f"- **[{a['title']}]({a['url']})** — {a['source']} • {fmt_time(a['published_at'])}")

st.caption("Sources: Hacker News (Algolia API) and Reddit hot posts. Data cached 5 minutes.")
