"""
জনগণের কণ্ঠস্বর — Flask Web Application
"""
import os
import json
import threading
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, abort
)

import database as db
import news_agent
from config import (
    SECRET_KEY, ADMIN_PASSWORD, AGENT_TOKEN,
    SITE_NAME, SITE_TAGLINE, SITE_URL, FB_PAGE,
    CATEGORIES, CATEGORY_MAP, DEBUG,
)

BDT = timezone(timedelta(hours=6))

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True


# ── Context Processors ─────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "site_name": SITE_NAME,
        "site_tagline": SITE_TAGLINE,
        "site_url": SITE_URL,
        "fb_page": FB_PAGE,
        "categories": CATEGORIES,
        "category_map": CATEGORY_MAP,
        "now": datetime.now(BDT),
    }


# ── Helpers ─────────────────────────────────────────────

def format_date(dt_str):
    """Format a datetime string for display."""
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now(BDT)
        diff = now - dt.replace(tzinfo=BDT)
        if diff.days > 7:
            return dt.strftime("%d %B %Y")
        elif diff.days > 0:
            return f"{diff.days} দিন আগে"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600} ঘণ্টা আগে"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60} মিনিট আগে"
        else:
            return "এইমাত্র"
    except Exception:
        return dt_str


def render_body_markdown(body_text):
    """Convert markdown-style subheadings (##) to HTML."""
    import re
    if not body_text:
        return ""
    # Split by lines
    lines = body_text.split('\n')
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Subheadings: ## শিরোনাম
        if line.startswith('## '):
            heading_text = line[3:].strip()
            html_parts.append(f'<h3 class="article-subheading">{heading_text}</h3>')
        else:
            html_parts.append(f'<p>{line}</p>')
    return '\n'.join(html_parts)


app.jinja_env.globals.update(format_date=format_date)
app.jinja_env.globals.update(render_body_markdown=render_body_markdown)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ── Routes: Public ──────────────────────────────────────

@app.route("/")
def home():
    """Homepage: hero + latest + category sections."""
    latest_with_image = db.get_posts(limit=6, with_image_first=True)
    latest = db.get_posts(limit=12)
    category_sections = {}
    for cat in CATEGORIES[:6]:
        posts = db.get_posts(category=cat["slug"], limit=4)
        if posts:
            category_sections[cat["slug"]] = {"info": cat, "posts": posts}
    return render_template("home.html",
                           hero_posts=latest_with_image[:3],
                           latest_posts=latest,
                           category_sections=category_sections)


@app.route("/category/<slug>")
def category_page(slug):
    """Category listing page."""
    if slug not in CATEGORY_MAP:
        abort(404)
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    posts = db.get_posts(category=slug, limit=per_page, offset=offset, with_image_first=True)
    cat_info = CATEGORY_MAP[slug]
    return render_template("category.html", posts=posts, cat_info=cat_info,
                           page=page, slug=slug)


@app.route("/article/<int:post_id>")
def article(post_id):
    """Single article page."""
    post = db.get_post(post_id)
    if not post:
        abort(404)
    db.increment_views(post_id)
    # Related posts
    related = db.get_posts(category=post["category"], limit=6)
    related = [r for r in related if r["id"] != post_id][:4]
    return render_template("article.html", post=post, related=related)


@app.route("/search")
def search():
    """Search page."""
    q = request.args.get("q", "").strip()
    posts = []
    if q:
        posts = db.search_posts(q, limit=30)
    return render_template("search.html", query=q, posts=posts)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# ── Routes: Admin ───────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("ভুল পাসওয়ার্ড!", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    """Admin dashboard."""
    total_posts = db.count_posts()
    total_views = db.get_total_views()
    cat_counts = db.count_posts_by_category()
    logs = db.get_agent_logs(limit=30)
    agent_enabled = db.get_setting("agent_enabled", "1") == "1"
    agent_interval = db.get_setting("agent_interval", "20")
    return render_template("admin.html",
                           total_posts=total_posts,
                           total_views=total_views,
                           cat_counts=cat_counts,
                           logs=logs,
                           agent_enabled=agent_enabled,
                           agent_interval=agent_interval)


@app.route("/admin/run-agent", methods=["POST"])
@admin_required
def admin_run_agent():
    """Manually trigger the agent."""
    def run():
        db.init_db()
        news_agent.run_agent(seed=False)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    flash("এজেন্ট চালু হয়েছে! কিছুক্ষণ অপেক্ষা করুন।", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/toggle-agent", methods=["POST"])
@admin_required
def admin_toggle_agent():
    enabled = db.get_setting("agent_enabled", "1")
    new_val = "0" if enabled == "1" else "1"
    db.set_setting("agent_enabled", new_val)
    state = "চালু" if new_val == "1" else "বন্ধ"
    flash(f"এজেন্ট এখন {state}!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/update-interval", methods=["POST"])
@admin_required
def admin_update_interval():
    interval = request.form.get("interval", "20", type=int)
    if 5 <= interval <= 120:
        db.set_setting("agent_interval", str(interval))
        flash(f"এজেন্ট ব্যবধান: {interval} মিনিট", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/<int:post_id>", methods=["POST"])
@admin_required
def admin_delete_post(post_id):
    db.delete_post(post_id)
    flash("পোস্ট মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_dashboard"))


# ── API / Cron Endpoints ───────────────────────────────

@app.route("/agent/run/<token>")
def agent_run(token):
    """Cron endpoint — runs agent in background thread."""
    if token != AGENT_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    def run():
        db.init_db()
        news_agent.run_agent(seed=False)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"ok": True, "posted": "started"})


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "posts": db.count_posts()})


@app.route("/sitemap.xml")
def sitemap():
    """Simple sitemap."""
    posts = db.get_posts(limit=500)
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    # Static pages
    for path in ["", "about", "privacy", "contact"]:
        xml_parts.append(f'<url><loc>{SITE_URL}/{path}</loc></url>')

    # Category pages
    for cat in CATEGORIES:
        xml_parts.append(f'<url><loc>{SITE_URL}/category/{cat["slug"]}</loc></url>')

    # Articles
    for post in posts:
        xml_parts.append(f'<url><loc>{SITE_URL}/article/{post["id"]}</loc></url>')

    xml_parts.append('</urlset>')
    return '\n'.join(xml_parts), 200, {"Content-Type": "application/xml"}


# ── Error Handlers ─────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ── Init ───────────────────────────────────────────────

with app.app_context():
    db.init_db()


def _auto_seed():
    """Auto-seed news on startup if database is empty."""
    import time
    time.sleep(2)  # Wait for app to fully start
    try:
        if db.count_posts() == 0:
            print("🌱 Database empty — auto-seeding news...")
            news_agent.run_agent(seed=True)
            print(f"🌱 Seeded {db.count_posts()} posts")
    except Exception as e:
        print(f"🌱 Auto-seed error: {e}")


# Start auto-seed in background thread
_seeder = threading.Thread(target=_auto_seed, daemon=True)
_seeder.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=DEBUG)
