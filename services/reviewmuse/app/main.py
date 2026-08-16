from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path('/data')
DB_PATH = DATA_DIR / 'reviewmuse.db'
OLLAMA_URL = os.getenv('REVIEWMUSE_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
MODEL = os.getenv('REVIEWMUSE_MODEL', 'qwen3:4b')
GOOGLE_REVIEW_URL = os.getenv('REVIEWMUSE_GOOGLE_REVIEW_URL', 'https://www.google.com/maps')

app = FastAPI(title='ReviewMuse', version='0.1.1')
app.mount('/static', StaticFiles(directory=BASE_DIR / 'static'), name='static')
env = Environment(loader=FileSystemLoader(BASE_DIR / 'templates'), autoescape=select_autoescape(['html']))

BUSINESSES = {
    'demo': {
        'name': 'ReviewMuse Demo Business',
        'location': 'Your local business',
        'google_review_url': GOOGLE_REVIEW_URL,
    }
}


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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            slug TEXT NOT NULL,
            event TEXT NOT NULL
        )'''
    )
    return conn


def log_event(slug: str, event: str) -> None:
    conn = db()
    try:
        conn.execute('INSERT INTO events(ts, slug, event) VALUES (?, ?, ?)', (int(time.time()), slug, event))
        conn.commit()
    finally:
        conn.close()


def render(name: str, **context: Any) -> HTMLResponse:
    template = env.get_template(name)
    return HTMLResponse(template.render(**context))


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


@app.get('/', response_class=HTMLResponse)
def landing() -> HTMLResponse:
    return render('landing.html')


@app.get('/r/{slug}', response_class=HTMLResponse)
def review_flow(slug: str) -> HTMLResponse:
    business = BUSINESSES.get(slug)
    if not business:
        return render('not_found.html', slug=slug)
    log_event(slug, 'opened')
    return render('review.html', slug=slug, business=business)


@app.get('/health')
def health() -> dict[str, Any]:
    return {'status': 'healthy', 'service': 'ReviewMuse', 'version': '0.1.1', 'model': MODEL}


@app.post('/api/event')
def event(payload: EventRequest) -> dict[str, bool]:
    log_event(payload.slug, payload.event)
    return {'ok': True}


@app.post('/api/generate')
async def generate(payload: GenerateRequest) -> JSONResponse:
    business = BUSINESSES.get(payload.slug)
    if not business:
        return JSONResponse({'error': 'Unknown business link.'}, status_code=404)

    log_event(payload.slug, 'generation_requested')
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
- Sound human and specific without becoming exaggerated.
- Aim for 70-140 words for natural/warm/detailed and 35-70 words for concise.
- Return only the review text, with no heading, quotation marks, or commentary.
'''

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f'{OLLAMA_URL}/api/generate',
                json={
                    'model': MODEL,
                    'prompt': prompt,
                    'stream': False,
                    'think': False,
                    'options': {'temperature': 0.55},
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

    log_event(payload.slug, 'generation_completed')
    return JSONResponse({'review': text, 'source': source})
