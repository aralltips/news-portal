"""
জনগণের কণ্ঠস্বর — Configuration
"""
import os

# --- Database ---
import os
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# If DATABASE_URL is set (Render PostgreSQL), use it; otherwise SQLite
DATABASE_PATH = os.environ.get("DATABASE_PATH", "news.db")

# --- Flask ---
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-secret-key-2026")
DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# --- Admin ---
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# --- Agent Token (for cron) ---
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "jknews-token-2026")

# --- AI (Gemini) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# --- Agent Settings ---
AGENT_INTERVAL_MINUTES = int(os.environ.get("AGENT_INTERVAL", "20"))
MAX_POSTS_PER_CATEGORY = int(os.environ.get("MAX_POSTS_PER_CAT", "8"))
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "15"))

# --- Site ---
SITE_NAME = "জনগণের কণ্ঠস্বর"
SITE_TAGLINE = "সত্যিকারের খবর, সবার জন্য"
SITE_URL = os.environ.get("SITE_URL", "https://janogoner-konthosor-qv2e.onrender.com")
FB_PAGE = "https://www.facebook.com/janagonerkonthosor"

# --- Categories ---
CATEGORIES = [
    {"slug": "bangladesh", "name": "বাংলাদেশ", "icon": "🇧🇩"},
    {"slug": "international", "name": "আন্তর্জাতিক", "icon": "🌍"},
    {"slug": "politics", "name": "রাজনীতি", "icon": "🏛️"},
    {"slug": "economy", "name": "অর্থনীতি", "icon": "📈"},
    {"slug": "technology", "name": "প্রযুক্তি", "icon": "💻"},
    {"slug": "sports", "name": "খেলাধুলা", "icon": "⚽"},
    {"slug": "entertainment", "name": "বিনোদন", "icon": "🎬"},
    {"slug": "education", "name": "শিক্ষা", "icon": "📚"},
    {"slug": "health", "name": "স্বাস্থ্য", "icon": "🏥"},
    {"slug": "lifestyle", "name": "জীবনযাত্রা", "icon": "🌿"},
]

CATEGORY_MAP = {c["slug"]: c for c in CATEGORIES}
CATEGORY_SLUGS = [c["slug"] for c in CATEGORIES]

# --- News Sources ---
RSS_FEEDS = {
    "bbc_bangla": {"url": "https://feeds.bbci.co.uk/bengali/rss.xml", "name": "BBC বাংলা", "default_cat": "international"},
    "prothom_alo": {"url": "https://www.prothomalo.com/feed/", "name": "প্রথম আলো", "default_cat": "bangladesh"},
    "channel_i": {"url": "https://www.channelionline.com/feed/", "name": "চ্যানেল আই", "default_cat": "bangladesh"},
    "bangla_tribune": {"url": "https://www.banglatribune.com/feed/rss.xml", "name": "বাংলা ট্রিবিউন", "default_cat": "bangladesh"},
    "samakal": {"url": "https://www.samakal.com/feed/rss.xml", "name": "সমকাল", "default_cat": "bangladesh"},
}

# --- Google News keywords per category ---
GOOGLE_NEWS_KEYWORDS = {
    "bangladesh": "বাংলাদেশ খবর",
    "international": "আন্তর্জাতিক খবর",
    "politics": "বাংলাদেশ রাজনীতি",
    "economy": "বাংলাদেশ অর্থনীতি",
    "technology": "প্রযুক্তি খবর",
    "sports": "ক্রিকেট ফুটবল খেলা",
    "entertainment": "বাংলা বিনোদন",
    "education": "শিক্ষা খবর বাংলাদেশ",
    "health": "স্বাস্থ্য খবর বাংলাদেশ",
    "lifestyle": "জীবনযাত্রা বাংলা",
}
