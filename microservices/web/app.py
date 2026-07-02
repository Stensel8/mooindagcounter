"""
Web-app: routes, validatie en teller-logica.

Dit bestand is IDENTIEK in beide varianten van deze repo (microservices en
bunny-libsql); het enige verschil zit in de datalaag (web/db.py). Wijzig je
hier iets, kopieer het dan 1-op-1 naar de andere variant.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

import db

# Laad omgevingsvariabelen uit .env (alleen lokaal; in productie komen ze via Docker env).
load_dotenv("./.env")

logger = logging.getLogger("uvicorn.error")

# Tijdzone voor het opslaan van datum/tijd bij elke increment.
AMS = ZoneInfo(os.getenv("TZ", "Europe/Amsterdam"))

# Maximale berichtlengte om de database te beschermen tegen oversized invoer.
MAX_MESSAGE_LENGTH = 300

# Identificatie van deze instantie: regio + pod-ID op Bunny.net Magic Containers
# (via de automatisch geinjecteerde BUNNYNET_MC_* variabelen), hostname elders.
# Wordt als X-Served-By header meegestuurd zodat zichtbaar is welke pod een
# request afhandelde — onmisbaar bij het debuggen van multi-region deployments.
SERVED_BY = "-".join(
    filter(None, (os.getenv("BUNNYNET_MC_REGION"), os.getenv("BUNNYNET_MC_PODID")))
) or os.getenv("HOSTNAME", "local")

# Sterke referenties naar achtergrondtaken zodat de GC ze niet vroegtijdig verwijdert.
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opent de databaseverbinding bij opstart; sluit netjes af bij afsluiten."""
    await db.startup()
    yield
    await db.shutdown()


app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)
templates = Jinja2Templates(directory="templates")

# Serveer bestanden uit de static/-map op het /static/-pad (CSS, afbeeldingen, favicon).
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Response-middleware ---

class ResponseHeadersMiddleware(BaseHTTPMiddleware):
    """
    Voegt standaard headers toe aan elke response:
    - 'Cache-Control: no-store' op HTML-responses. Zonder deze header slaat
      Bunny.net (en andere CDN's/browsers) pagina's op, waardoor de teller een
      verouderde stand toont na een nieuwe invoer. JSON- en statische
      bestanden worden hier niet door geraakt.
    - 'X-Served-By' op alle responses: welke regio/pod dit request afhandelde.
      Zo is direct te controleren of alle regio's dezelfde database zien.
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if "text/html" in response.headers.get("content-type", ""):
            response.headers["cache-control"] = "no-store"
        response.headers["x-served-by"] = SERVED_BY
        return response


app.add_middleware(ResponseHeadersMiddleware)


# --- Foutafhandeling --- Mooindag...

@app.exception_handler(StarletteHTTPException)
async def http_exception(request: Request, exc: StarletteHTTPException):
    """Vangt HTTP-fouten op en geeft altijd JSON terug."""
    return JSONResponse(
        {"error": exc.detail or "HTTP error"},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """
    Vangnet voor alle onverwachte fouten die niet als HTTP-uitzondering zijn afgehandeld.
    Logt de fout en toont de offline-pagina met een 500-status.
    """
    logger.error("Onverwachte fout: %s", exc)
    return templates.TemplateResponse(
        request, "db_offline.html", {}, status_code=500
    )


# --- Applicatielogica --- Mooindag!

async def push_to_discord(counter: int, message: str, timestamp: datetime) -> None:
    """
    Stuurt een melding naar het Discord-webhook na een succesvolle increment.
    Wordt aangeroepen via asyncio.create_task() zodat de gebruiker niet hoeft
    te wachten op de Discord-response voordat de redirect plaatsvindt.
    """
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
    """
    Haalt het echte IP-adres van de bezoeker op.
    Bunny.net stuurt de keten van proxies mee in X-Forwarded-For;
    de eerste waarde daarin is het originele client-IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Routes --- Mooindag...

@app.get("/")
async def index(request: Request):
    """Toont de hoofdpagina met de huidige tellerstand."""
    counter = await db.get_latest_counter()
    if counter is None:
        return templates.TemplateResponse(request, "db_offline.html", {}, status_code=503)
    return templates.TemplateResponse(request, "index.html", {"counter": counter})


@app.post("/increment")
async def increment(request: Request, message: str = Form("")):
    """
    Verwerkt een nieuwe increment-invoer vanuit het formulier.
    Valideert het bericht (niet leeg, niet te lang, niet al eerder ingevoerd),
    slaat het op in de DB en stuurt een Discord-melding op de achtergrond.
    Gebruik status 303 (See Other) zodat de browser na de redirect een GET doet
    in plaats van de POST te herhalen bij het verversen van de pagina.
    """
    timestamp = datetime.now(tz=AMS)
    counter = await db.get_latest_counter()
    if counter is None:
        return templates.TemplateResponse(request, "db_offline.html", {}, status_code=503)

    message = message.strip().lower()

    # Valideer invoer voordat de DB wordt benaderd.
    if not message:
        return templates.TemplateResponse(
            request, "index.html", {"counter": counter, "error_message": "empty"}
        )
    if len(message) > MAX_MESSAGE_LENGTH:
        return templates.TemplateResponse(
            request, "index.html", {"counter": counter, "error_message": "too_long"}
        )
    if await db.message_exists(message):
        return templates.TemplateResponse(
            request, "index.html", {"counter": counter, "error_message": "duplicate"}
        )

    new_id = await db.save_counter(
        message,
        timestamp.date(),
        timestamp.time().replace(microsecond=0),
        get_client_ip(request),
    )
    if new_id is None:
        return templates.TemplateResponse(request, "db_offline.html", {}, status_code=503)

    # Stuur Discord-melding op de achtergrond; blokkeer de response niet.
    task = asyncio.create_task(push_to_discord(new_id, message, timestamp))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return RedirectResponse(url="/", status_code=303)


@app.get("/overview")
async def overview(request: Request):
    """Toont een tabel met alle counts, van nieuwste naar oudste."""
    data = await db.get_all_counters()
    if data is None:
        return templates.TemplateResponse(request, "db_offline.html", {}, status_code=503)
    return templates.TemplateResponse(request, "overview.html", {"data": data})


@app.get("/robots.txt")
async def robots_txt():
    """Serveert robots.txt vanuit de static/-map op het verwachte root-pad."""
    return FileResponse("static/robots.txt", media_type="text/plain")


@app.get("/healthz")
async def healthz():
    """
    Statuscheck voor de loadbalancer en uptime-monitor.
    Geeft 200 + {"status": "ok"} als de DB bereikbaar is, anders 503.
    """
    if await db.ping():
        return JSONResponse({"status": "ok", "served_by": SERVED_BY})
    return JSONResponse({"status": "db_unavailable", "served_by": SERVED_BY}, status_code=503)


# --- JSON API --- Mooindag!

@app.get("/api/counts")
async def api_counts():
    """Geeft alle counts terug als JSON-array, gesorteerd van nieuwste naar oudste."""
    counters = await db.get_all_counters()
    if counters is None:
        return JSONResponse({"error": "Database unavailable"}, status_code=503)
    return JSONResponse(
        [{"id": c["id"], "message": c["message"], "date": c["date"]} for c in counters]
    )


@app.get("/api/counts/{id}")
async def get_api_count(id: int):
    """Geeft een specifieke count terug als JSON op basis van ID."""
    entry = await db.get_counter(id)
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({k: v for k, v in entry.items() if k != "client_ip"})


@app.delete("/api/counts/{id}")
async def delete_api_count(id: int):
    """Verwijdert een count via de API. Geeft 503 terug als de DB niet bereikbaar is."""
    ok = await db.delete_counter(id)
    if not ok:
        return JSONResponse({"error": "Database unavailable"}, status_code=503)
    return JSONResponse({"message": f"Record {id} deleted"})
