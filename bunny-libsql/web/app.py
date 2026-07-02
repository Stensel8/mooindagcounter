"""
Web-app: routes, validatie en teller-logica.

Dit bestand is IDENTIEK in beide varianten van deze repo; het enige verschil
zit in de datalaag (web/db.py). Wijzig je hier iets, kopieer het dan 1-op-1
naar de andere variant — de CI-check "variant-sync" dwingt dit af.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

import db

# .env is alleen voor lokaal ontwikkelen; in productie komt alles via Docker env.
if os.path.exists("./.env"):
    load_dotenv("./.env")

logger = logging.getLogger("uvicorn.error")

AMS = ZoneInfo(os.getenv("TZ", "Europe/Amsterdam"))
MAX_MESSAGE_LENGTH = 300

# Verwijder-wachtwoord: alleen via env/secret, nooit in de code. Niet
# ingesteld betekent verwijderen uitgeschakeld. Na een juist wachtwoord is
# de browser TRUST_SECONDS vertrouwd via een HMAC-getekende cookie.
DELETE_PASSWORD = os.getenv("DELETE_PASSWORD", "")
TRUST_COOKIE = "mooindag_trust"
TRUST_SECONDS = 600

# Live-updates: hoe vaak een worker de database peilt zolang er websocket-
# kijkers zijn. De pods in verschillende regio's delen geen geheugen; de
# (gerepliceerde) database is hun enige gedeelde waarheid, dus dit pollen
# ís de synchronisatie. Eén SELECT per interval per worker — verwaarloosbaar.
LIVE_POLL_SECONDS = float(os.getenv("LIVE_POLL_SECONDS", "4"))

# Welke regio/pod dit request afhandelde (Bunny injecteert BUNNYNET_MC_*);
# gaat als X-Served-By header mee zodat multi-region te debuggen is.
SERVED_BY = "-".join(
    filter(None, (os.getenv("BUNNYNET_MC_REGION"), os.getenv("BUNNYNET_MC_PODID")))
) or os.getenv("HOSTNAME", "local")

# Sterke referenties naar achtergrondtaken zodat de GC ze niet opruimt.
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.startup()
    yield
    await db.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


class ResponseHeadersMiddleware(BaseHTTPMiddleware):
    """
    'Cache-Control: no-store' op HTML zodat CDN's/browsers nooit een oude
    tellerstand tonen, en 'X-Served-By' op alles voor multi-region debugging.
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["cache-control"] = "no-store"
        response.headers["x-served-by"] = SERVED_BY
        return response


app.add_middleware(ResponseHeadersMiddleware)


# --- Foutafhandeling --- Mooindag...

def offline_page(request: Request):
    """Vriendelijke foutpagina die vertelt wat er misgaat (uit db.last_error)."""
    return templates.TemplateResponse(
        request, "db_offline.html", {"reden": db.last_error}, status_code=503
    )


def offline_json():
    return JSONResponse(
        {"error": db.last_error or "de database is even niet beschikbaar"},
        status_code=503,
    )


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Vangnet: log de fout en toon de foutpagina in plaats van een kale 500."""
    logger.error("Onverwachte fout bij %s %s: %s", request.method, request.url.path, exc)
    return templates.TemplateResponse(
        request, "db_offline.html", {"reden": "er ging onverwacht iets stuk"}, status_code=500
    )


# --- Verwijder-beveiliging --- Mooindag!

def _sign(expires: int) -> str:
    return hmac.new(DELETE_PASSWORD.encode(), str(expires).encode(), hashlib.sha256).hexdigest()


def _is_trusted(request: Request) -> bool:
    """Heeft deze browser een geldige, niet-verlopen vertrouwenscookie?"""
    expires, _, signature = request.cookies.get(TRUST_COOKIE, "").partition(".")
    return (
        bool(DELETE_PASSWORD)
        and expires.isdigit()
        and int(expires) > time.time()
        and hmac.compare_digest(signature, _sign(int(expires)))
    )


# --- Live-updates via WebSocket --- Mooindag!

_ws_clients: set[WebSocket] = set()
_poller: asyncio.Task | None = None


async def _poll_loop():
    """
    Draait alleen zolang er kijkers zijn en stopt daarna vanzelf (geen
    kijkers = geen queries = geen kosten). Bij elke verandering van de
    tellerstand gaan de nieuwe berichten naar alle lokale kijkers; andere
    regio's zien dezelfde verandering via hun eigen poller.
    """
    last_id = None
    while _ws_clients:
        latest = await db.get_latest_counter()
        if latest is not None and latest != last_id:
            nieuw = []
            if last_id is not None and latest > last_id:
                nieuw = await db.get_counters_since(last_id)
            payload = {
                "counter": latest,
                "nieuw": [{"id": r["id"], "message": r["message"]} for r in nieuw],
            }
            for client in list(_ws_clients):
                try:
                    await client.send_json(payload)
                except Exception:
                    _ws_clients.discard(client)
            last_id = latest
        await asyncio.sleep(LIVE_POLL_SECONDS)


@app.websocket("/ws")
async def websocket_live(ws: WebSocket):
    """Duwt tellerstand + nieuwe berichten naar de browser zodra die veranderen."""
    global _poller
    await ws.accept()
    _ws_clients.add(ws)
    if _poller is None or _poller.done():
        _poller = asyncio.create_task(_poll_loop())
    try:
        while True:
            await ws.receive_text()  # clients sturen niets; dit wacht op de disconnect
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)


# --- Applicatielogica --- Mooindag!

async def push_to_discord(counter: int, message: str, timestamp: datetime) -> None:
    """Discord-melding na een increment; draait als achtergrondtaak."""
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                url,
                json={
                    "content": (
                        f"Counter: {counter}\n"
                        f"Datum: {timestamp.strftime('%d-%m-%Y')}\n"
                        f"Tijd: {timestamp.strftime('%H:%M')}\n"
                        f"{message.capitalize()}"
                    )
                },
            )
    except httpx.RequestError as e:
        logger.warning("Discord webhook mislukt: %s", e)


def get_client_ip(request: Request) -> str:
    """Client-IP; Bunny.net zet het originele IP voorop in X-Forwarded-For."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Routes --- Mooindag...

@app.get("/")
async def index(request: Request):
    counter = await db.get_latest_counter()
    if counter is None:
        return offline_page(request)
    return templates.TemplateResponse(request, "index.html", {"counter": counter})


@app.post("/increment")
async def increment(request: Request, message: str = Form("")):
    """
    Valideert en bewaart een nieuw bericht. Redirect met 303 (See Other)
    zodat verversen na het opslaan de POST niet herhaalt.
    """
    timestamp = datetime.now(tz=AMS)
    counter = await db.get_latest_counter()
    if counter is None:
        return offline_page(request)

    message = message.strip().lower()
    if not message:
        error = "empty"
    elif len(message) > MAX_MESSAGE_LENGTH:
        error = "too_long"
    elif await db.message_exists(message):
        error = "duplicate"
    else:
        error = None
    if error:
        return templates.TemplateResponse(
            request, "index.html", {"counter": counter, "error_message": error}
        )

    new_id = await db.save_counter(
        message,
        timestamp.date(),
        timestamp.time().replace(microsecond=0),
        get_client_ip(request),
    )
    if new_id is None:
        return offline_page(request)

    task = asyncio.create_task(push_to_discord(new_id, message, timestamp))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return RedirectResponse(url="/", status_code=303)


@app.get("/overview")
async def overview(request: Request):
    data = await db.get_all_counters()
    if data is None:
        return offline_page(request)
    return templates.TemplateResponse(request, "overview.html", {"data": data})


@app.get("/robots.txt")
async def robots_txt():
    return FileResponse("static/robots.txt", media_type="text/plain")


# --- JSON API --- Mooindag!

@app.get("/api/counts")
async def api_counts():
    counters = await db.get_all_counters()
    if counters is None:
        return offline_json()
    return JSONResponse(
        [{"id": c["id"], "message": c["message"], "date": c["date"]} for c in counters]
    )


@app.get("/api/counts/{id}")
async def get_api_count(id: int):
    entry = await db.get_counter(id)
    if not entry:
        return JSONResponse({"error": "Dat berichtje bestaat niet (meer)."}, status_code=404)
    return JSONResponse({k: v for k, v in entry.items() if k != "client_ip"})


@app.delete("/api/counts/{id}")
async def delete_api_count(id: int, request: Request):
    """
    Verwijdert een count. Vereist het verwijder-wachtwoord (header
    X-Delete-Password) of een nog geldige vertrouwenscookie; bij een juist
    wachtwoord wordt de browser TRUST_SECONDS vertrouwd.
    """
    if not DELETE_PASSWORD:
        return JSONResponse(
            {"error": "Verwijderen staat uit: er is geen DELETE_PASSWORD ingesteld."},
            status_code=403,
        )
    trusted = _is_trusted(request)
    given = request.headers.get("X-Delete-Password", "")
    if not trusted and not hmac.compare_digest(given.encode(), DELETE_PASSWORD.encode()):
        return JSONResponse({"error": "Dat wachtwoord klopt niet."}, status_code=401)

    if not await db.delete_counter(id):
        return offline_json()

    response = JSONResponse({"message": f"Record {id} verwijderd"})
    if not trusted:
        expires = int(time.time()) + TRUST_SECONDS
        response.set_cookie(
            TRUST_COOKIE,
            f"{expires}.{_sign(expires)}",
            max_age=TRUST_SECONDS,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response
