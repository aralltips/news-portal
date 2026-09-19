"""
Blogger Auto-Publisher
Publishes articles to Google Blogger using Blogger API v3.
"""
import os
import json
import urllib.request
import urllib.parse

# These come from Google Cloud Console OAuth2
BLOGGER_CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID", "")
BLOGGER_CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET", "")
BLOGGER_REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN", "")
BLOGGER_BLOG_ID = os.environ.get("BLOGGER_BLOG_ID", "8693447816270729007")

BLOGGER_API = "https://www.googleapis.com/blogger/v3"


def _get_access_token():
    """Get a fresh access token using the refresh token."""
    if not all([BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN]):
        return None

    data = urllib.parse.urlencode({
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()

    try:
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("access_token")
    except Exception as e:
        print(f"[Blogger] Token refresh failed: {e}")
        return None


def _api_call(method, path, body=None):
    """Make an API call to Blogger."""
    token = _get_access_token()
    if not token:
        return None

    url = f"{BLOGGER_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[Blogger] API error: {e}")
        return None


def is_configured():
    """Check if Blogger integration is configured."""
    return all([
        BLOGGER_CLIENT_ID,
        BLOGGER_CLIENT_SECRET,
        BLOGGER_REFRESH_TOKEN,
        BLOGGER_BLOG_ID
    ])


def _download_image_as_base64(image_url):
    """Download image and convert to base64 data URI."""
    try:
        req = urllib.request.Request(image_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg")
            import base64
            b64 = base64.b64encode(data).decode()
            return f"data:{ct};base64,{b64}"
    except Exception as e:
        print(f"[Blogger] Image download failed: {e}")
        return None


def _build_html(title, summary, body, image_url, source_name, source_url, category):
    """Build Blogger-friendly HTML from article content."""
    import re
    body_html = body
    body_html = re.sub(r'## (.+)', r'<h3 style="color:#c0392b;font-size:1.2em;margin:20px 0 10px;font-weight:700;">\1</h3>', body_html)
    paragraphs = [p.strip() for p in body_html.split('\n\n') if p.strip()]
    body_html = ""
    for p in paragraphs:
        if p.startswith('<h3'):
            body_html += p
        else:
            body_html += f"<p style='line-height:1.8;font-size:16px;margin:12px 0;'>{p}</p>"

    cat_emojis = {
        'bangladesh': '🇧🇩', 'international': '🌍', 'politics': '⚖️',
        'economy': '💰', 'sports': '⚽', 'entertainment': '🎬',
        'technology': '💻', 'education': '📚', 'health': '🏥', 'lifestyle': '🌿'
    }
    cat_names = {
        'bangladesh': 'বাংলাদেশ', 'international': 'আন্তর্জাতিক', 'politics': 'রাজনীতি',
        'economy': 'অর্থনীতি', 'sports': 'খেলাধুলা', 'entertainment': 'বিনোদন',
        'technology': 'প্রযুক্তি', 'education': 'শিক্ষা', 'health': 'স্বাস্থ্য', 'lifestyle': 'লাইফস্টাইল'
    }
    emoji = cat_emojis.get(category, '📰')
    cat_name = cat_names.get(category, category)

    # Image HTML - use direct URL (Blogger will pick it up as thumbnail)
    img_html = ""
    if image_url and image_url.startswith("http"):
        img_html = f'<img src="{image_url}" style="width:100%;border-radius:12px;margin-bottom:20px;" />'

    html = f"""
<div style="max-width:720px;margin:0 auto;font-family:'Noto Sans Bengali',sans-serif;">

{img_html}

<div style="background:#f0f4f8;padding:16px 20px;border-radius:10px;border-left:4px solid #c0392b;margin-bottom:24px;">
<p style="margin:0;font-size:17px;line-height:1.7;color:#333;">{summary}</p>
</div>

{body_html}

<div style="background:#f8f9fa;padding:14px 20px;border-radius:8px;margin-top:24px;font-size:14px;color:#666;">
<b>{emoji} বিভাগ:</b> {cat_name}
{'| <b>📰 উৎস:</b> ' + source_name if source_name else ''}
{'| <a href="' + source_url + '">🔗 মূল উৎস</a>' if source_url else ''}
</div>

<p style="text-align:center;margin-top:24px;font-size:13px;color:#999;">
জনগণের কণ্ঠস্বর — সত্যিকারের খবর, সবার জন্য<br/>
<a href="https://janogoner-konthosor-qv2e.onrender.com/" style="color:#c0392b;">🌐 ওয়েবসাইট দেখুন</a>
</p>
</div>"""
    return html


def _clean_title(title):
    """Remove source names from title for Blogger display."""
    import re
    clean = title.strip()
    clean = re.sub(r'\s*[\|]\s*.*$', '', clean)
    clean = re.sub(r'\s*[-–—:]\s*[\w\s\.]+$,', '', clean)
    clean = re.sub(r'\s*[-–—]\s*(প্রথম আলো|BBC|NTV|BSS|RTV|Channel|Daily|Sangbad|সমকাল|ইনকিলাব|যুগান্তর|দৈনিক|Inqilab|Bhorer|Bangladesh|Prothom|Alo|News|net|com|Gramer|Kagoj|Share|Bazar|শেয়ার|বিজ|খবর|সংবাদ|সংস্থা|বাসস|গ্রামের|কাগজ|জাতীয়).*$', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+[-]\s+[A-Za-z\u0980-\u09FF\s\.]+$', '', clean)
    clean = re.sub(r'\s*[\|–—-]\s*$', '', clean).strip()
    return clean if clean and len(clean) > 10 else title.strip()


def publish_post(title, summary, body, image_url="", category="bangladesh",
                 source_name="", source_url=""):
    """Publish an article to Blogger. Returns post URL or None."""
    if not is_configured():
        return None

    html = _build_html(title, summary, body, image_url, source_name, source_url, category)

    post_body = {
        "kind": "blogger#post",
        "blog": {"id": BLOGGER_BLOG_ID},
        "title": _clean_title(title),
        "content": html,
        "labels": [category, "AI News"],
    }

    result = _api_call("POST", f"/blogs/{BLOGGER_BLOG_ID}/posts", post_body)
    if result and "url" in result:
        return result["url"]
    return None