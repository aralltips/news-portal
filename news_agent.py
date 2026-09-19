"""
জনগণের কণ্ঠস্বর — AI News Agent v3
Professional article generation with images embedded in content.
"""
import hashlib
import re
import time
import json
import threading
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import database as db
from config import (
    GEMINI_API_KEY, CATEGORIES, CATEGORY_SLUGS, CATEGORY_MAP,
    RSS_FEEDS, GOOGLE_NEWS_KEYWORDS, MAX_POSTS_PER_CATEGORY,
    MAX_POSTS_PER_RUN, SITE_NAME,
)

try:
    from config import ARTICLE_MAX_RSS
except Exception:
    ARTICLE_MAX_RSS = 10

# Blogger auto-publish
try:
    import blogger_publisher
except Exception:
    blogger_publisher = None

# Thread lock to prevent concurrent runs
_agent_lock = threading.Lock()

BDT = timezone(timedelta(hours=6))


# ── Utility ────────────────────────────────────────────

def _hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _now_str():
    return datetime.now(BDT).strftime("%Y-%m-%d %H:%M:%S")


def _clean_html(html_text):
    """Strip HTML tags."""
    return re.sub(r'<[^>]+>', '', html_text or '').strip()


def _truncate(text, max_len=500):
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(' ', 1)[0] + '...'


def _log(msg):
    ts = _now_str()
    line = f"[{ts}] {msg}"
    print(line)
    try:
        db.log_agent(line)
    except Exception:
        pass


# ── Fetching: RSS Feeds ─────────────────────────────────

def _extract_image_from_html(html_text):
    if not html_text:
        return ""
    matches = re.findall(r'<img[^>]+src=["\']([^"\']+)', html_text, re.IGNORECASE)
    for m in matches:
        if m.startswith("data:") or "1x1" in m or "pixel" in m or "spacer" in m:
            continue
        if any(ext in m.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
            return m
    for m in matches:
        if not m.startswith("data:") and "1x1" not in m:
            return m
    return ""


def _fetch_rss(url, timeout=15):
    import urllib.request
    import xml.etree.ElementTree as ET
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        ns_media = "{http://search.yahoo.com/mrss/}"

        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "")
            desc_text = _clean_html(desc)
            pub = item.findtext("pubDate", "")

            img = ""
            for tag in [f"{ns_media}content", f"{ns_media}thumbnail"]:
                el = item.find(tag)
                if el is not None:
                    img = el.get("url", "") or el.get("medium", "")
                    if img:
                        break
            if not img:
                thumb = item.find("thumbnail")
                if thumb is not None:
                    img = thumb.get("url", "") or (thumb.text or "").strip()
            if img and "ichef.bbci.co.uk" in img and "/240/" in img:
                img = img.replace("/240/", "/640/")
            if not img:
                for enc in item.findall("enclosure"):
                    enc_type = enc.get("type", "")
                    enc_url = enc.get("url", "")
                    if enc_url and ("image" in enc_type or any(ext in enc_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif'])):
                        img = enc_url
                        break
            if not img:
                for img_tag in ["image", f"{ns_media}image"]:
                    img_el = item.find(img_tag)
                    if img_el is not None:
                        img = img_el.findtext("url", "") or img_el.get("url", "")
                        if img:
                            break
            if not img and desc:
                img = _extract_image_from_html(desc)
            if not img:
                content_encoded = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", "")
                if content_encoded:
                    img = _extract_image_from_html(content_encoded)

            if title and link:
                items.append({"title": title, "url": link, "text": desc_text, "image": img, "published": pub})

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", ns):
            title = (entry.findtext("atom:title", "", ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            summary = _clean_html(entry.findtext("atom:summary", "", ns))
            content = entry.findtext("atom:content", "", ns)
            text = _clean_html(content) or summary

            img = ""
            for tag in [f"{ns_media}content", f"{ns_media}thumbnail"]:
                el = entry.find(tag)
                if el is not None:
                    img = el.get("url", "")
                    if img:
                        break
            if not img:
                thumb = entry.find("thumbnail")
                if thumb is not None:
                    img = thumb.get("url", "") or (thumb.text or "").strip()
            if not img and content:
                img = _extract_image_from_html(content)
            if not img:
                img = _extract_image_from_html(entry.findtext("atom:summary", "", ns))

            if title and link:
                items.append({"title": title, "url": link, "text": text, "image": img, "published": ""})
    except Exception as e:
        _log(f"RSS fetch error ({url[:60]}): {e}")
    return items


def fetch_all_rss():
    all_items = []
    for feed_id, feed_info in RSS_FEEDS.items():
        _log(f"Fetching RSS: {feed_info['name']}")
        items = _fetch_rss(feed_info["url"])
        for item in items:
            item["source_name"] = feed_info["name"]
            item["default_cat"] = feed_info["default_cat"]
        all_items.extend(items)
        _log(f"  → {len(items)} items from {feed_info['name']}")
        time.sleep(0.5)
    return all_items


def fetch_google_news(category):
    keyword = GOOGLE_NEWS_KEYWORDS.get(category, "বাংলাদেশ খবর")
    url = f"https://news.google.com/rss/search?q={quote_plus(keyword)}&hl=bn&gl=BD&ceid=BD:bn"
    items = _fetch_rss(url)
    for item in items:
        item["source_name"] = "Google News"
        item["default_cat"] = category
        resolved = _resolve_gnews_url(item["url"])
        if resolved:
            item["url"] = resolved
    return items


def _resolve_gnews_url(url, timeout=8):
    import urllib.request
    try:
        if "news.google.com" not in url:
            return None
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, method="HEAD")
        req.add_header("Accept", "*/*")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.url
            if final_url != url and "news.google.com" not in final_url:
                return final_url
    except urllib.error.HTTPError as e:
        if hasattr(e, 'headers') and 'Location' in e.headers:
            loc = e.headers['Location']
            if "news.google.com" not in loc:
                return loc
    except Exception:
        pass
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.url
            if final_url != url and "news.google.com" not in final_url:
                return final_url
    except Exception:
        pass
    return None


def _fetch_og_image(url, timeout=10):
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            if "image/" in ct:
                return url
            data = resp.read(200000).decode("utf-8", errors="ignore")

        for pattern in [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        ]:
            match = re.search(pattern, data, re.IGNORECASE)
            if match:
                img = match.group(1).strip()
                if img.startswith("http"):
                    return img

        for pattern in [
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        ]:
            match = re.search(pattern, data, re.IGNORECASE)
            if match:
                img = match.group(1).strip()
                if img.startswith("http"):
                    return img

        article_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)', data, re.IGNORECASE)
        for img in article_imgs:
            if img.startswith("data:") or "1x1" in img or "pixel" in img:
                continue
            skip = ['logo', 'icon', 'sprite', 'avatar', 'favicon', 'badge', 'button', 'ad-', '-ad', 'banner']
            img_lower = img.lower()
            if any(p in img_lower for p in skip):
                continue
            if any(ext in img_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                if img.startswith("http"):
                    return img
                try:
                    from urllib.parse import urljoin
                    return urljoin(url, img)
                except Exception:
                    pass
    except Exception as e:
        _log(f"og:image fetch error ({url[:50]}): {e}")
    return ""


# ── Category Detection ─────────────────────────────────

_KEYWORD_TO_CATEGORY = {
    "bangladesh": ["বাংলাদেশ", "ঢাকা", "সিলেট", "চট্টগ্রাম", "খুলনা", "রাজশাহী", "বরিশাল", "রংপুর", "ময়মনসিংহ"],
    "international": ["আন্তর্জাতিক", "বিশ্ব", "যুক্তরাষ্ট্র", "চীন", "ভারত", "রাশিয়া", "ইউরোপ", "মধ্যপ্রাচ্য"],
    "politics": ["রাজনীতি", "সরকার", "মন্ত্রী", "সংসদ", "নির্বাচন", "দল", "প্রধানমন্ত্রী", "বিরোধী"],
    "economy": ["অর্থনীতি", "ব্যাংক", "টাকা", "বাজেট", "রপ্তানি", "আমদানি", "শেয়ার", "বিনিয়োগ", "জিডিপি"],
    "technology": ["প্রযুক্তি", "মোবাইল", "ইন্টারনেট", "এআই", "AI", "কম্পিউটার", "অ্যাপ", "ডিজিটাল"],
    "sports": ["ক্রিকেট", "ফুটবল", "খেলা", "ম্যাচ", "বিশ্বকাপ", "টি-টোয়েন্টি", "প্রিমিয়ার লিগ"],
    "entertainment": ["বিনোদন", "সিনেমা", "গান", "নাটক", "অভিনেতা", "অভিনেত্রী", "সেলিব্রিটি", "সিরিজ"],
    "education": ["শিক্ষা", "বিশ্ববিদ্যালয়", "পরীক্ষা", "ভর্তি", "ছাত্র", "শিক্ষক", "এসএসসি", "এইচএসসি"],
    "health": ["স্বাস্থ্য", "হাসপাতাল", "ডাক্তার", "ওষুধ", "রোগ", "করোনা", "ভ্যাকসিন", "চিকিৎসা"],
    "lifestyle": ["জীবনযাত্রা", "ভ্রমণ", "খাবার", "ফ্যাশন", "সৌন্দর্য", "রান্না"],
}


def detect_category(title, text, default_cat="bangladesh"):
    combined = (title + " " + text).lower()
    scores = {}
    for cat, keywords in _KEYWORD_TO_CATEGORY.items():
        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score > 0:
            scores[cat] = score
    if scores:
        return max(scores, key=scores.get)
    return default_cat if default_cat in CATEGORY_SLUGS else "bangladesh"


# ── Professional Article Generator v3 ───────────────────

# Category-specific analysis templates
_CATEGORY_CONTEXT = {
    "bangladesh": {
        "hook": ["দেশের রাজনৈতিক ও সামাজিক পরিস্থিতিতে এই ঘটনা গুরুত্বপূর্ণ প্রভাব ফেলতে পারে।",
                 "বাংলাদেশের অভ্যন্তরীণ বিষয়ে এই খবর সকলের মনোযোগ কেড়ে নিয়েছে।",
                 "সমাজের বিভিন্ন স্তরের মানুষ এই বিষয়ে প্রতিক্রিয়া দেখাচ্ছেন।"],
        "context": "বাংলাদেশের বর্তমান প্রেক্ষাপটে এই ঘটনা অত্যন্ত তাৎপর্যপূর্ণ। দেশের অভ্যন্তরীণ রাজনৈতিক, সামাজিক ও অর্থনৈতিক পরিস্থিতির সঙ্গে এর সম্পর্ক রয়েছে।",
        "analysis": "বিশ্লেষকরা মনে করেন, এই ঘটনা বাংলাদেশের অভ্যন্তরীণ রাজনীতি ও সমাজে দূরপ্রসারী প্রভাব ফেলতে পারে। সরকারি ও বেসরকারি পর্যায়ে এর প্রতিক্রিয়া দেখা যাচ্ছে।",
    },
    "international": {
        "hook": ["বিশ্ব রাজনীতিতে এই ঘটনা নতুন মোড় নিয়ে এসেছে।",
                 "আন্তর্জাতিক সম্প্রদায় এই বিষয়ে উদ্বিগ্ন।",
                 "বৈশ্বিক পরিস্থিতিতে এর গুরুত্ব অনেক।"],
        "context": "আন্তর্জাতিক রাজনীতি ও কূটনীতির প্রেক্ষাপটে এই ঘটনা বিশেষ গুরুত্বপূর্ণ। বিভিন্ন দেশ ও আন্তর্জাতিক সংস্থা এই বিষয়ে নজরদারি করছে।",
        "analysis": "আন্তর্জাতিক বিশ্লেষকরা মনে করেন, এই ঘটনা বৈশ্বিক রাজনীতিতে নতুন সমীকরণ তৈরি করতে পারে। বিভিন্ন মহাশক্তির প্রতিক্রিয়া এর ওপর নির্ভর করবে।",
    },
    "politics": {
        "hook": ["রাজনৈতিক মঞ্চে এই ঘটনা আলোড়ন সৃষ্টি করেছে।",
                 "সরকার ও বিরোধী দল উভয়ই এই বিষয়ে মন্তব্য করেছে।",
                 "রাজনৈতিক বিশ্লেষকরা এই ঘটনাকে গুরুত্বপূর্ণ মনে করছেন।"],
        "context": "বাংলাদেশের রাজনৈতিক পরিস্থিতির প্রেক্ষাপটে এই ঘটনা অত্যন্ত তাৎপর্যপূর্ণ। সংসদীয় ও সংসদ বহির্ভূত রাজনীতিতে এর প্রতিফলন দেখা যাচ্ছে।",
        "analysis": "রাজনৈতিক বিশ্লেষকদের মতে, এই ঘটনা আগামী দিনের রাজনীতিতে গুরুত্বপূর্ণ ভূমিকা রাখতে পারে। বিভিন্ন রাজনৈতিক দলের ভবিষ্যৎ কৌশল এর ওপর নির্ভরশীল।",
    },
    "economy": {
        "hook": ["অর্থনৈতিক খাতে এই খবর ব্যাপক প্রতিক্রিয়া সৃষ্টি করেছে।",
                 "ব্যবসা-বাণিজ্যে এর প্রভাব পড়তে পারে।",
                 "বিনিয়োগকারীরা এই বিষয়ে সতর্ক।"],
        "context": "বাংলাদেশের অর্থনৈতিক প্রেক্ষাপটে এই খবর অত্যন্ত গুরুত্বপূর্ণ। শেয়ারবাজার, ব্যাংকিং সেক্টর ও বিনিয়োগ খাতে এর প্রতিফলন দেখা যেতে পারে।",
        "analysis": "অর্থনীতিবিদরা মনে করেন, এই পরিবর্তন দেশের অর্থনৈতিক প্রবৃদ্ধিতে গুরুত্বপূর্ণ ভূমিকা রাখতে পারে। বিনিয়োগকারীদের সচেতন থাকা প্রয়োজন।",
    },
    "sports": {
        "hook": ["ক্রীড়া জগতে এই খবর আলোড়ন সৃষ্টি করেছে।",
                 "খেলোয়াড় ও ভক্তরা এই বিষয়ে উৎসাহী।",
                 "ক্রীড়াঙ্গনে এটি একটি গুরুত্বপূর্ণ মুহূর্ত।"],
        "context": "বাংলাদেশ ও আন্তর্জাতিক ক্রীড়াঙ্গনের প্রেক্ষাপটে এই খবর বিশেষ গুরুত্বপূর্ণ। ক্রিকেট, ফুটবলসহ বিভিন্ন খেলায় এর প্রতিফলন দেখা যাচ্ছে।",
        "analysis": "ক্রীড়া বিশ্লেষকরা মনে করেন, এই ঘটনা বাংলাদেশের ক্রীড়াঙ্গনে নতুন সম্ভাবনা তৈরি করতে পারে। খেলোয়াড় ও কোচদের প্রতিক্রিয়া গুরুত্বপূর্ণ।",
    },
    "technology": {
        "hook": ["প্রযুক্তি খাতে এই উন্নয়ন গুরুত্বপূর্ণ।",
                 "ডিজিটাল বাংলাদেশ গড়ার লক্ষ্যে এটি একটি পদক্ষেপ।",
                 "তরুণ প্রজন্মের জন্য এই খবর বিশেষ তাৎপর্যপূর্ণ।"],
        "context": "বাংলাদেশের প্রযুক্তি খাতের দ্রুত বিকাশের প্রেক্ষাপটে এই খবর অত্যন্ত গুরুত্বপূর্ণ। স্টার্টআপ ইকোসিস্টেম ও ডিজিটাল অর্থনীতিতে এর প্রভাব পড়তে পারে।",
        "analysis": "প্রযুক্তি বিশেষজ্ঞরা মনে করেন, এই উন্নয়ন বাংলাদেশের ডিজিটাল ভবিষ্যৎ গড়তে গুরুত্বপূর্ণ ভূমিকা রাখবে।",
    },
    "entertainment": {
        "hook": ["বিনোদন জগতে এই খবর ব্যাপক আলোচনা সৃষ্টি করেছে।",
                 "দর্শকমহলে এই খবর নিয়ে উৎসুকতা বেড়েছে।",
                 "সোশ্যাল মিডিয়ায় এই খবর ভাইরাল হচ্ছে।"],
        "context": "বাংলাদেশের বিনোদন শিল্পের দ্রুত বিকাশের প্রেক্ষাপটে এই খবর বিশেষ গুরুত্বপূর্ণ। চলচ্চিত্র, সংগীত ও ডিজিটাল কন্টেন্ট খাতে এর প্রতিফলন দেখা যাচ্ছে।",
        "analysis": "বিনোদন শিল্পের বিশ্লেষকরা মনে করেন, এই পরিবর্তন দর্শকদের পছন্দ ও শিল্পের ভবিষ্যৎ দিকনির্দেশনায় গুরুত্বপূর্ণ ভূমিকা রাখবে।",
    },
    "education": {
        "hook": ["শিক্ষা খাতে এই খবর গুরুত্বের সঙ্গে বিবেচনা করা প্রয়োজন।",
                 "শিক্ষার্থী ও অভিভাবকদের জন্য এটি তাৎপর্যপূর্ণ।",
                 "শিক্ষাব্যবস্থায় এর প্রভাব পড়তে পারে।"],
        "context": "বাংলাদেশের শিক্ষাব্যবস্থার বর্তমান প্রেক্ষাপটে এই খবর অত্যন্ত গুরুত্বপূর্ণ। প্রাথমিক থেকে উচ্চশিক্ষা পর্যন্ত সকল স্তরে এর প্রতিফলন দেখা যেতে পারে।",
        "analysis": "শিক্ষাবিদরা মনে করেন, এই পরিবর্তন শিক্ষার্থীদের ভবিষ্যৎ গড়তে গুরুত্বপূর্ণ ভূমিকা রাখতে পারে। শিক্ষক ও অভিভাবকদের সচেতন থাকা জরুরি।",
    },
    "health": {
        "hook": ["স্বাস্থ্য খাতে এই খবর সকলের জন্য গুরুত্বপূর্ণ।",
                 "জনস্বাস্থ্যে এর প্রভাব পড়তে পারে।",
                 "স্বাস্থ্য সচেতনতায় এই খবর কার্যকরী।"],
        "context": "বাংলাদেশের স্বাস্থ্যখাতের বর্তমান চ্যালেঞ্জের প্রেক্ষাপটে এই খবর অত্যন্ত গুরুত্বপূর্ণ। সাধারণ মানুষের স্বাস্থ্যসেবা পাওয়ার ওপর এর প্রতিফলন দেখা যেতে পারে।",
        "analysis": "স্বাস্থ্য বিশেষজ্ঞরা মনে করেন, এই বিষয়ে সাধারণ মানুষের সচেতনতা বৃদ্ধি করা প্রয়োজন। প্রতিটি পরিবারের জন্য এই তথ্য জানা জরুরি।",
    },
    "lifestyle": {
        "hook": ["জীবনযাত্রার মানোন্নয়নে এই খবর কার্যকরী হতে পারে।",
                 "দৈনন্দিন জীবনে এর প্রয়োগ রয়েছে।",
                 "স্বাস্থ্যকর জীবনযাপনের জন্য এই তথ্য গুরুত্বপূর্ণ।"],
        "context": "বর্তমান সময়ে জীবনযাত্রার মান উন্নয়নের প্রেক্ষাপটে এই খবর বিশেষ গুরুত্বপূর্ণ। স্বাস্থ্যকর অভ্যাস ও জীবনযাপন পদ্ধতিতে এর প্রভাব রয়েছে।",
        "analysis": "জীবনযাত্রা বিশেষজ্ঞরা মনে করেন, এই তথ্য পাঠকদের দৈনন্দিন জীবনে ইতিবাচক পরিবর্তন আনতে পারে।",
    },
}


def _generate_professional_article(title, original_text, category_name, source_name=""):
    """
    Generate a professional Bengali news article.
    Uses original text intelligently, adds context and analysis.
    """
    text = (original_text or "").strip()
    if not text or len(text) < 20:
        text = title

    # Split into meaningful sentences
    sentences = [s.strip() for s in re.split(r'[।!?\.]+', text) if s.strip() and len(s.strip()) > 15]

    if len(sentences) < 2:
        sentences = [text, "এই বিষয়ে বিস্তারিত তথ্য সংগ্রহ করা হচ্ছে।"]

    random.seed(hash(title))

    # Get category context
    cat_key = "bangladesh"
    for k in _CATEGORY_CONTEXT:
        if k in category_name.lower() or category_name in ["বাংলাদেশ", "আন্তর্জাতিক", "রাজনীতি", "অর্থনীতি", "খেলাধুলা", "বিনোদন", "প্রযুক্তি", "শিক্ষা", "স্বাস্থ্য", "লাইফস্টাইল"]:
            cat_map = {"বাংলাদেশ": "bangladesh", "আন্তর্জাতিক": "international", "রাজনীতি": "politics",
                       "অর্থনীতি": "economy", "খেলাধুলা": "sports", "বিনোদন": "entertainment",
                       "প্রযুক্তি": "technology", "শিক্ষা": "education", "স্বাস্থ্য": "health", "লাইফস্টাইল": "lifestyle"}
            cat_key = cat_map.get(category_name, k)
            break

    ctx = _CATEGORY_CONTEXT.get(cat_key, _CATEGORY_CONTEXT["bangladesh"])

    # ── Summary ──
    summary_parts = sentences[:2] if len(sentences) >= 2 else [sentences[0]]
    summary = "। ".join(summary_parts)
    if not summary.endswith("।"):
        summary += "।"
    summary += " " + random.choice(ctx["hook"])

    # ── Body ──
    body = []

    # Lead — rewrite the first sentence naturally
    lead = sentences[0]
    body.append(f"## লিড")
    body.append("")
    if source_name and source_name not in lead:
        body.append(f"{lead} — এই খবরটি {source_name} সহ বিভিন্ন সংবাদমাধ্যমে প্রকাশিত হয়েছে।")
    else:
        body.append(f"{lead} — এই ঘটনা বর্তমানে ব্যাপক আলোচনায় রয়েছে।")
    body.append("")

    # Context
    body.append("## প্রেক্ষাপট")
    body.append("")
    if len(sentences) >= 3:
        body.append(f"{sentences[1]}।")
    body.append(ctx["context"])
    body.append("")

    # Details — use remaining original sentences
    body.append("## বিস্তারিত বিবরণ")
    body.append("")
    detail_sentences = sentences[2:6] if len(sentences) > 3 else sentences[1:]
    if detail_sentences:
        for s in detail_sentences:
            if len(s) > 20:
                body.append(f"{s}।")
    else:
        body.append(f"এই ঘটনাটি সম্পর্কে আরও তথ্য পাওয়ার সাথে সাথে পাঠকদের জানানো হবে। বিস্তারিত বিবরণের জন্য মূল উৎসের লিংক দেখুন।")
    body.append("")

    # Stakeholder reactions
    body.append("## সংশ্লিষ্ট পক্ষের প্রতিক্রিয়া")
    body.append("")
    body.append(f"এই বিষয়ে বিভিন্ন মহল থেকে প্রতিক্রিয়া এসেছে। সংশ্লিষ্ট কর্তৃপক্ষ, বিশেষজ্ঞ এবং সাধারণ মানুষ সকলেই এই ঘটনায় গভীর মনোযোগ দিচ্ছেন। সরকারি ও বেসরকারি পর্যায়ে এই বিষয়ে আলোচনা চলছে।")
    body.append("")

    # Expert opinion
    body.append("## বিশেষজ্ঞ মতামত")
    body.append("")
    body.append(f"বিশ্লেষক ও বিশেষজ্ঞরা এই বিষয়ে তাদের মতামত দিয়েছেন। তারা মনে করেন, এই ঘটনা বা বিষয়টি সময়ের গুরুত্বপূর্ণ একটি দিক তুলে ধরেছে যা সকলের জানা প্রয়োজন।")
    body.append("")

    # Impact & Analysis
    body.append("## প্রভাব ও বিশ্লেষণ")
    body.append("")
    body.append(ctx["analysis"])
    body.append("")

    # Regional/International context
    body.append("## আঞ্চলিক ও আন্তর্জাতিক প্রেক্ষাপট")
    body.append("")
    body.append(f"আঞ্চলিক ও আন্তর্জাতিক প্রেক্ষাপটে এই ঘটনার তাৎপর্য বিশেষভাবে বিবেচনা করা প্রয়োজন। দক্ষিণ এশিয়াসহ বৃহত্তর আন্তর্জাতিক পরিমণ্ডলে এর প্রতিফলন দেখা যেতে পারে।")
    body.append("")

    # Next steps
    body.append("## পরবর্তী পদক্ষেপ")
    body.append("")
    body.append(f"এই বিষয়ে আরও তথ্য ও আপডেট জানতে আমাদের সাথে যুক্ত থাকুন। সংশ্লিষ্ট কর্তৃপক্ষের পরবর্তী সিদ্ধান্ত, বিবৃতি ও পদক্ষেপের ওপর নজর রাখা প্রয়োজন। বিস্তারিত জানতে নিচের মূল উৎসের লিংক দেখুন।")
    body.append("")

    # Conclusion
    body.append("## উপসংহার")
    body.append("")
    hook = random.choice(ctx["hook"])
    body.append(f"সামগ্রিকভাবে, {title} — এই বিষয়টি বর্তমান প্রেক্ষাপটে অত্যন্ত গুরুত্বপূর্ণ। {hook} পাঠকদের সঠিক ও নির্ভরযোগ্য তথ্যের ভিত্তিতে এই ঘটনাকে বিশ্লেষণ করার আহ্বান জানানো হচ্ছে। জনগণের কণ্ঠস্বর এই বিষয়ে আপডেট দিয়ে যেতে থাকবে।")
    body.append("")
    if source_name:
        body.append(f"**মূল উৎস:** {source_name}")

    return summary, "\n".join(body)


def _ai_rewrite(title, original_text, category_name):
    """Use Gemini AI to write article. Falls back to professional generator."""
    if not GEMINI_API_KEY:
        return None, None  # Will use _generate_professional_article instead

    import urllib.request

    prompt = f"""আপনি একজন অত্যন্ত অভিজ্ঞ ও জনপ্রিয় বাংলা সাংবাদিক। আপনার লেখা পড়লে পাঠক মুগ্ধ হয়, সময় ব্যয় করতে রাজি হয়। নিচের খবরের তথ্য দেখে একটি প্রফেশনাল, আকর্ষণীয় ও বিস্তারিত বাংলা নিউজ আর্টিকেল লিখুন যা AdSense-রেডি।

**খবরের শিরোনাম:** {title}
**বিভাগ:** {category_name}

**মূল তথ্য:**
{original_text[:2500]}

**লেখার নিয়মাবলী:**

১. **সারসংক্ষেপ (summary):** ৩-৪ বাক্যের আকর্ষণীয়, কৌতূহলোদ্দীপক সারসংক্ষেপ লিখুন। পাঠক যেন ভাবে "এটা তো পড়তেই হবে!" — এমনভাবে লিখুন। শেষ বাক্যে একটা hook দিন যেমন "এই ঘটনা কেন এত গুরুত্বপূর্ণ তা জানতে পুরো আর্টিকেলটি পড়ুন।"

২. **আর্টিকেল বডি:** ৭ থেকে ১০টি অনুচ্ছেদে আর্টিকেল লিখুন, মোট ৬০০-৮০০ শব্দ। প্রতিটি অনুচ্ছেদের আগে ## দিয়ে সাবহেডিং দিন।

৩. **আর্টিকেলের গঠন:**
   - ## লিড: সবচেয়ে গুরুত্বপূর্ণ তথ্য — কী ঘটেছে, কে, কখন, কোথায় (৩-৪ বাক্য)
   - ## প্রেক্ষাপট: ঘটনার পটভূমি, আগের ইতিহাস, কেন এটি গুরুত্বপূর্ণ (৩-৫ বাক্য)
   - ## বিস্তারিত বিবরণ: মূল ঘটনার সব তথ্য বিস্তারিত (৪-৬ বাক্য)
   - ## সংশ্লিষ্ট পক্ষের প্রতিক্রিয়া: কে কী বলেছে (২-৪ বাক্য)
   - ## বিশেষজ্ঞ মতামত: বিশ্লেষক/বিশেষজ্ঞদের দৃষ্টিভঙ্গি (২-৩ বাক্য)
   - ## প্রভাব ও বিশ্লেষণ: এই ঘটনার সম্ভাব্য দূরপ্রসারী প্রভাব (৩-৪ বাক্য)
   - ## আঞ্চলিক ও আন্তর্জাতিক প্রেক্ষাপট: বৃহত্তর প্রেক্ষাপটে এর অবস্থান (২-৩ বাক্য)
   - ## পরবর্তী পদক্ষেপ: এরপর কী হতে পারে, কী করা উচিত (২-৩ বাক্য)
   - ## উপসংহার: সামগ্রিক চিত্র, পাঠকের জন্য বার্তা (২-৩ বাক্য)

৪. **গুরুত্বপূর্ণ নিয়ম:**
   - মূল তথ্যের বাইরে নতুন তথ্য উদ্ভাবন করবেন না
   - প্রেক্ষাপট ও বিশ্লেষণ যোগ করুন — সাধারণ জ্ঞান ও যুক্তির ভিত্তিতে
   - প্রতিটি অনুচ্ছেদ ৩-৬ বাক্য হবে, ছোট ও পরিষ্কার
   - সরল, সাবলীল, আকর্ষণীয় বাংলায় লিখুন
   - পাঠককে জোড়া দিয়ে রাখার মতো ভাষা ব্যবহার করুন
   - প্রতিটি অনুচ্ছেদে পর্যাপ্ত তথ্য ও বিশ্লেষণ দিন

**আউটপুট ফরম্যাট (JSON):**
```json
{{
  "summary": "৩-৪ বাক্যের আকর্ষণীয়, কৌতূহলোদ্দীপক সারসংক্ষেপ",
  "body": "## লিড\\n\\nবিস্তারিত প্রথম অনুচ্ছেদ...\\n\\n## প্রেক্ষাপট\\n\\nদ্বিতীয় অনুচ্ছেদ...\\n\\n(এভাবে চলবে)"
}}
```

শুধুমাত্র JSON আউটপুট দিন, অন্য কিছু না।"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 3000,
        }
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            json_match2 = re.search(r'\{[\s\S]*"summary"[\s\S]*"body"[\s\S]*\}', text)
            if json_match2:
                result = json.loads(json_match2.group())
            else:
                _log(f"AI parse failed — raw: {text[:200]}")
                return None, None

        summary = result.get("summary", "").strip()
        body = result.get("body", "").strip()

        if summary and body:
            _log(f"AI wrote: summary={len(summary)} chars, body={len(body)} chars, ~{len(body.split())} words")
            return summary, body
        return None, None

    except Exception as e:
        _log(f"Gemini error: {e}")
        return None, None


# ── Main Agent Logic ───────────────────────────────────

def _process_items(items, source_label="RSS"):
    posted = 0
    for item in items:
        if posted >= MAX_POSTS_PER_RUN:
            break

        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        text = item.get("text", "").strip()
        image = item.get("image", "").strip()
        source_name = item.get("source_name", source_label)
        default_cat = item.get("default_cat", "bangladesh")

        if not title or not url:
            continue

        url_hash = _hash(url)
        if db.url_hash_exists(url_hash):
            continue

        category = detect_category(title, text, default_cat)

        # Get image if missing
        if not image:
            fetch_url = url
            if "news.google.com" in url:
                resolved = _resolve_gnews_url(url)
                if resolved:
                    fetch_url = resolved
            image = _fetch_og_image(fetch_url)

        # Generate article
        cat_name = CATEGORY_MAP.get(category, {}).get("name", "বাংলাদেশ")

        # Try Gemini AI first
        ai_summary, ai_body = _ai_rewrite(title, text, cat_name)

        if ai_summary and ai_body:
            summary = ai_summary
            body = ai_body
            ai_written = 1
        else:
            # Professional template fallback
            summary, body = _generate_professional_article(title, text, cat_name, source_name)
            ai_written = 0

        success = db.insert_post(
            title=title,
            summary=summary,
            body=body,
            image_url=image,
            category=category,
            source_name=source_name,
            source_url=url,
            url_hash=url_hash,
            ai_written=ai_written,
        )
        if success:
            posted += 1
            _log(f"✅ Posted: {title[:60]}... [{category}] {'(AI)' if ai_written else '(template)'}")

            # Auto-publish to Blogger
            if blogger_publisher and blogger_publisher.is_configured():
                try:
                    blogger_url = blogger_publisher.publish_post(
                        title=title,
                        summary=summary,
                        body=body,
                        image_url=image,
                        category=category,
                        source_name=source_name,
                        source_url=url,
                    )
                    if blogger_url:
                        _log(f"📢 Blogger: {blogger_url}")
                    else:
                        _log(f"⚠️ Blogger publish failed: {title[:40]}")
                except Exception as e:
                    _log(f"⚠️ Blogger error: {e}")

            time.sleep(1)

    return posted


def run_agent(seed=False):
    if not _agent_lock.acquire(blocking=False):
        _log("⏭ Agent already running, skipping.")
        return {"status": "already_running"}

    try:
        _log("🚀 Agent run started")
        total_posted = 0

        # 1. RSS feeds
        _log("── Phase 1: RSS Feeds ──")
        rss_items = fetch_all_rss()
        seen_urls = set()
        unique_rss = []
        for item in rss_items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                unique_rss.append(item)
        posted = _process_items(unique_rss, "RSS")
        total_posted += posted
        _log(f"RSS phase: {posted} posts")

        # 2. Google News
        _log("── Phase 2: Google News ──")
        cats = CATEGORY_SLUGS if seed else CATEGORY_SLUGS[:5]
        for cat in cats:
            _log(f"Google News: {cat}")
            gn_items = fetch_google_news(cat)
            unique_gn = []
            for item in gn_items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    unique_gn.append(item)
            posted = _process_items(unique_gn, "Google News")
            total_posted += posted
            _log(f"  → {posted} posts from {cat}")
            time.sleep(1)

        _log(f"🏁 Agent run complete: {total_posted} new posts")
        return {"status": "ok", "posted": total_posted}

    except Exception as e:
        _log(f"❌ Agent error: {e}")
        return {"status": "error", "error": str(e)}

    finally:
        _agent_lock.release()


if __name__ == "__main__":
    import sys
    db.init_db()
    seed = "--seed" in sys.argv
    result = run_agent(seed=seed)
    print(json.dumps(result, indent=2, ensure_ascii=False))