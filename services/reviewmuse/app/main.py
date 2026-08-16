from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path('/data')
UPLOAD_DIR = DATA_DIR / 'uploads'
DB_PATH = DATA_DIR / 'reviewmuse.db'
OLLAMA_URL = os.getenv('REVIEWMUSE_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
MODEL = os.getenv('REVIEWMUSE_MODEL', 'qwen3:1.7b')
GOOGLE_REVIEW_URL = os.getenv('REVIEWMUSE_GOOGLE_REVIEW_URL', 'https://www.google.com/maps')
ADMIN_PASSWORD = os.getenv('REVIEWMUSE_ADMIN_PASSWORD', 'reviewmuse-local')
SESSION_SECRET = os.getenv('REVIEWMUSE_SESSION_SECRET', 'reviewmuse-local-session-change-before-public').encode()
SESSION_COOKIE = 'rm_business_session'
VISITOR_COOKIE = 'rm_visitor'
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title='ReviewMuse', version='0.3.1')
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
app.mount('/uploads', StaticFiles(directory=UPLOAD_DIR), name='uploads')
env = Environment(loader=FileSystemLoader(BASE_DIR / 'templates'), autoescape=select_autoescape(['html']))


class GenerateRequest(BaseModel):
    slug: str = 'demo'
    rating: int = Field(ge=1, le=5)
    highlights: list[str] = Field(default_factory=list)
    details: str = Field(default='', max_length=1200)
    tone: str = Field(default='natural', pattern='^(natural|warm|concise|detailed)$')


class EventRequest(BaseModel):
    slug: str = 'demo'
    event: str = Field(max_length=80)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db()
    try:
        conn.execute(
            '''CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                slug TEXT NOT NULL,
                event TEXT NOT NULL,
                visitor TEXT DEFAULT ''
            )'''
        )
        event_columns = {row['name'] for row in conn.execute('PRAGMA table_info(events)').fetchall()}
        if 'visitor' not in event_columns:
            conn.execute("ALTER TABLE events ADD COLUMN visitor TEXT DEFAULT ''")

        conn.execute(
            '''CREATE TABLE IF NOT EXISTS businesses (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                headline TEXT NOT NULL DEFAULT '',
                intro TEXT NOT NULL DEFAULT '',
                accent_color TEXT NOT NULL DEFAULT '#6157e8',
                logo_path TEXT NOT NULL DEFAULT '',
                cover_path TEXT NOT NULL DEFAULT '',
                google_review_url TEXT NOT NULL,
                highlight_options TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )'''
        )
        now = int(time.time())
        conn.execute(
            '''INSERT OR IGNORE INTO businesses
               (slug, name, location, headline, intro, accent_color, google_review_url,
                highlight_options, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'demo',
                'ReviewMuse Demo Business',
                'Your local business',
                'Tell us about your experience.',
                'A few quick prompts can help you turn what happened into a review that sounds like you.',
                '#6157e8',
                GOOGLE_REVIEW_URL,
                'Friendly staff,Fast service,Quality,Communication,Cleanliness,Value,Professionalism,Could be improved',
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


init_db()


def render(name: str, **context: Any) -> HTMLResponse:
    template = env.get_template(name)
    return HTMLResponse(template.render(**context))


def get_business(slug: str) -> dict[str, Any] | None:
    conn = db()
    try:
        row = conn.execute('SELECT * FROM businesses WHERE slug = ?', (slug,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    business = dict(row)
    business['highlights'] = [x.strip() for x in business['highlight_options'].split(',') if x.strip()]
    return business


def visitor_id(request: Request) -> str:
    value = request.cookies.get(VISITOR_COOKIE, '').strip()
    if re.fullmatch(r'[a-f0-9-]{36}', value):
        return value
    return str(uuid.uuid4())


def log_event(slug: str, event: str, visitor: str = '') -> None:
    conn = db()
    try:
        conn.execute(
            'INSERT INTO events(ts, slug, event, visitor) VALUES (?, ?, ?, ?)',
            (int(time.time()), slug, event, visitor),
        )
        conn.commit()
    finally:
        conn.close()


def make_session(slug: str) -> str:
    expires = int(time.time()) + 12 * 60 * 60
    payload = f'{slug}|{expires}'
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}|{signature}'


def session_slug(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, '')
    try:
        slug, expires_raw, signature = token.split('|', 2)
        payload = f'{slug}|{expires_raw}'
        expected = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires_raw) < int(time.time()):
            return None
        return slug
    except (ValueError, TypeError):
        return None


def require_business(request: Request, slug: str) -> RedirectResponse | None:
    if session_slug(request) != slug:
        return RedirectResponse(f'/business/login?slug={slug}', status_code=303)
    return None


def analytics(slug: str) -> dict[str, Any]:
    conn = db()
    try:
        rows = conn.execute(
            'SELECT event, visitor, ts FROM events WHERE slug = ? ORDER BY ts DESC',
            (slug,),
        ).fetchall()
    finally:
        conn.close()

    events = [dict(row) for row in rows]
    opens = sum(1 for e in events if e['event'] == 'opened')

    def unique_for(names: set[str]) -> int:
        visitors = {e['visitor'] for e in events if e['event'] in names and e['visitor']}
        return len(visitors)

    unique_visitors = unique_for({'opened'})
    started = unique_for({'assisted_selected', 'self_write_selected'})
    review_ready = unique_for({'draft_shown', 'self_draft_shown'})
    continued = unique_for({'google_handoff'})
    ai_drafts = sum(1 for e in events if e['event'] == 'generation_completed')
    conversion = round((continued / unique_visitors * 100), 1) if unique_visitors else 0.0

    now = datetime.now(timezone.utc)
    days: list[dict[str, Any]] = []
    max_count = 1
    for offset in range(13, -1, -1):
        day_ts = int(now.timestamp()) - offset * 86400
        key = datetime.fromtimestamp(day_ts, timezone.utc).strftime('%Y-%m-%d')
        label = datetime.fromtimestamp(day_ts, timezone.utc).strftime('%b %d')
        day_events = [
            e for e in events
            if datetime.fromtimestamp(e['ts'], timezone.utc).strftime('%Y-%m-%d') == key
        ]
        opens_day = sum(1 for e in day_events if e['event'] == 'opened')
        handoffs_day = sum(1 for e in day_events if e['event'] == 'google_handoff')
        max_count = max(max_count, opens_day)
        days.append({'label': label, 'opens': opens_day, 'handoffs': handoffs_day})
    for day in days:
        day['height'] = max(6, round(day['opens'] / max_count * 100)) if day['opens'] else 3

    labels = {
        'opened': 'Opened review link',
        'assisted_selected': 'Started with AI assistance',
        'self_write_selected': 'Started writing independently',
        'generation_requested': 'Requested an AI draft',
        'generation_completed': 'AI draft completed',
        'draft_shown': 'Review draft ready',
        'self_draft_shown': 'Self-written review ready',
        'google_handoff': 'Continued to Google',
        'copied_again': 'Copied review again',
    }
    recent = [
        {
            'label': labels.get(e['event'], e['event'].replace('_', ' ').title()),
            'time': datetime.fromtimestamp(e['ts'], timezone.utc).strftime('%b %d, %H:%M UTC'),
        }
        for e in events[:20]
    ]

    return {
        'opens': opens,
        'unique_visitors': unique_visitors,
        'started': started,
        'review_ready': review_ready,
        'continued': continued,
        'ai_drafts': ai_drafts,
        'conversion': conversion,
        'days': days,
        'recent': recent,
    }


def fallback_review(rating: int, highlights: list[str], details: str) -> str:
    sentiment = {
        1: 'I had a disappointing experience',
        2: 'My experience fell short of what I expected',
        3: 'My experience was mixed overall',
        4: 'I had a very good experience',
        5: 'I had an excellent experience',
    }[rating]
    pieces = [sentiment + '.']
    if highlights:
        pieces.append('What stood out to me was ' + ', '.join(x.lower() for x in highlights[:4]) + '.')
    if details.strip():
        pieces.append(details.strip())
    pieces.append('This reflects my own experience and what mattered most to me.')
    return ' '.join(pieces)


def clean_text(value: str, limit: int) -> str:
    return ' '.join(value.strip().split())[:limit]


async def save_image(slug: str, kind: str, upload: UploadFile | None, max_bytes: int) -> str | None:
    if not upload or not upload.filename:
        return None
    allowed = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/webp': '.webp',
    }
    ext = allowed.get(upload.content_type or '')
    if not ext:
        raise ValueError('Images must be PNG, JPG, or WebP.')
    content = await upload.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f'{kind.title()} image is too large.')
    filename = f'{slug}-{kind}{ext}'
    (UPLOAD_DIR / filename).write_bytes(content)
    return f'/uploads/{filename}'


@app.get('/', response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return render('landing.html')


@app.get('/r/{slug}', response_class=HTMLResponse)
def review_flow(slug: str, request: Request) -> HTMLResponse:
    business = get_business(slug)
    if not business:
        return render('not_found.html', slug=slug)
    visitor = visitor_id(request)
    log_event(slug, 'opened', visitor)
    response = render('review.html', slug=slug, business=business)
    if request.cookies.get(VISITOR_COOKIE) != visitor:
        response.set_cookie(
            VISITOR_COOKIE,
            visitor,
            max_age=365 * 86400,
            httponly=True,
            samesite='lax',
        )
    return response


@app.get('/health')
def health() -> dict[str, Any]:
    return {'status': 'healthy', 'service': 'ReviewMuse', 'version': '0.3.1', 'model': MODEL}


@app.post('/api/event')
def event(payload: EventRequest, request: Request) -> dict[str, bool]:
    log_event(payload.slug, payload.event, visitor_id(request))
    return {'ok': True}


@app.post('/api/generate')
async def generate(payload: GenerateRequest, request: Request) -> JSONResponse:
    business = get_business(payload.slug)
    if not business:
        return JSONResponse({'error': 'Unknown business link.'}, status_code=404)

    visitor = visitor_id(request)
    log_event(payload.slug, 'generation_requested', visitor)
    prompt = f'''You are ReviewMuse, an ethical review-writing assistant.
Write a first-person customer review for {business['name']} using ONLY the customer's supplied experience.

Customer rating: {payload.rating}/5
Selected themes: {', '.join(payload.highlights) if payload.highlights else 'none selected'}
Customer notes: {payload.details.strip() or 'No additional notes.'}
Requested style: {payload.tone}

Rules:
- Preserve the customer's true sentiment. Never turn a negative or mixed experience into a positive one.
- Never invent employee names, products, events, wait times, prices, or facts the customer did not provide.
- Do not mention AI, ReviewMuse, star manipulation, incentives, or marketing language.
- Sound natural and specific without exaggeration.
- Aim for 60-110 words for natural/warm/detailed and 30-60 words for concise.
- Return only the review text, with no heading, quotation marks, or commentary.
'''

    try:
        async with httpx.AsyncClient(timeout=75) as client:
            response = await client.post(
                f'{OLLAMA_URL}/api/generate',
                json={
                    'model': MODEL,
                    'prompt': prompt,
                    'stream': False,
                    'think': False,
                    'keep_alive': '10m',
                    'options': {'temperature': 0.55, 'num_predict': 180},
                },
            )
            response.raise_for_status()
            text = response.json().get('response', '').strip()
            if not text:
                raise RuntimeError('Ollama returned an empty response')
        source = 'local-ai'
    except Exception:
        text = fallback_review(payload.rating, payload.highlights, payload.details)
        source = 'fallback'

    log_event(payload.slug, 'generation_completed', visitor)
    return JSONResponse({'review': text, 'source': source})


@app.get('/business/login', response_class=HTMLResponse)
def business_login(request: Request, slug: str = 'demo'):
    if session_slug(request) == slug and get_business(slug):
        return RedirectResponse(f'/business/{slug}', status_code=303)
    return render('business_login.html', slug=slug, error='')


@app.post('/business/login', response_class=HTMLResponse)
def business_login_submit(slug: str = Form(...), password: str = Form(...)):
    business = get_business(slug)
    if not business or not hmac.compare_digest(password, ADMIN_PASSWORD):
        return render(
            'business_login.html',
            slug=slug,
            error='That business link or password is not correct.',
        )
    response = RedirectResponse(f'/business/{slug}', status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        make_session(slug),
        max_age=12 * 60 * 60,
        httponly=True,
        samesite='lax',
    )
    return response


@app.post('/business/logout')
def business_logout() -> RedirectResponse:
    response = RedirectResponse('/business/login', status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get('/business/{slug}', response_class=HTMLResponse)
def business_dashboard(slug: str, request: Request, saved: int = 0):
    denied = require_business(request, slug)
    if denied:
        return denied
    business = get_business(slug)
    if not business:
        return RedirectResponse('/business/login', status_code=303)
    return render(
        'business_dashboard.html',
        business=business,
        stats=analytics(slug),
        saved=bool(saved),
        request_base=str(request.base_url).rstrip('/'),
    )


@app.post('/business/{slug}/settings', response_class=HTMLResponse)
async def business_settings(
    slug: str,
    request: Request,
    name: str = Form(...),
    location: str = Form(''),
    headline: str = Form(''),
    intro: str = Form(''),
    accent_color: str = Form('#6157e8'),
    google_review_url: str = Form(...),
    highlight_options: str = Form(''),
    logo: UploadFile | None = File(default=None),
    cover: UploadFile | None = File(default=None),
):
    denied = require_business(request, slug)
    if denied:
        return denied
    business = get_business(slug)
    if not business:
        return RedirectResponse('/business/login', status_code=303)

    accent_color = accent_color.strip()
    if not HEX_COLOR.fullmatch(accent_color):
        accent_color = business['accent_color']
    google_review_url = google_review_url.strip()
    if not google_review_url.startswith('https://'):
        google_review_url = business['google_review_url']

    try:
        logo_path = await save_image(slug, 'logo', logo, 2 * 1024 * 1024) or business['logo_path']
        cover_path = await save_image(slug, 'cover', cover, 5 * 1024 * 1024) or business['cover_path']
    except ValueError as exc:
        return render(
            'business_dashboard.html',
            business=business,
            stats=analytics(slug),
            saved=False,
            error=str(exc),
            request_base=str(request.base_url).rstrip('/'),
        )

    highlights = [clean_text(x, 40) for x in highlight_options.split(',') if clean_text(x, 40)]
    if not highlights:
        highlights = business['highlights']
    highlights = highlights[:12]

    conn = db()
    try:
        conn.execute(
            '''UPDATE businesses
               SET name = ?, location = ?, headline = ?, intro = ?, accent_color = ?,
                   logo_path = ?, cover_path = ?, google_review_url = ?, highlight_options = ?, updated_at = ?
               WHERE slug = ?''',
            (
                clean_text(name, 100) or business['name'],
                clean_text(location, 120),
                clean_text(headline, 140),
                clean_text(intro, 360),
                accent_color,
                logo_path,
                cover_path,
                google_review_url,
                ','.join(highlights),
                int(time.time()),
                slug,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f'/business/{slug}?saved=1', status_code=303)
