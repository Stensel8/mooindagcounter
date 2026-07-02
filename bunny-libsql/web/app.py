import asyncio
import base64
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


# --- Bunny Database (libSQL) verbinding ---
#
# Bunny Database spreekt het standaard libSQL/sqld "Hrana over HTTP" protocol:
# statements gaan als JSON naar POST {LIBSQL_URL}/v2/pipeline met een Bearer
# token — precies wat Bunny's eigen client-libraries ook doen. Er is geen
# officiele Python SDK, maar het protocol is klein genoeg om hier direct met
# httpx te spreken, zonder extra dependencies.

# Schema wordt door de app zelf aangemaakt als het nog niet bestaat (SQLite-
# dialect). AUTOINCREMENT garandeert dat verwijderde ID's nooit hergebruikt
# worden, zodat de teller (hoogste ID) nooit terugloopt door een delete.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""

# Gedeelde HTTP-client met connection pooling; aangemaakt in lifespan.
_client: httpx.AsyncClient | None = None

# Sterke referenties naar achtergrondtaken zodat de GC ze niet vroegtijdig verwijdert.
_background_tasks: set[asyncio.Task] = set()


def _base_url() -> str:
    """
    Normaliseert LIBSQL_URL naar een http(s)-URL.
    Bunny geeft URL's in de vorm libsql://<id>.lite.bunnydb.net; dat is
    hetzelfde endpoint over HTTPS. Voor lokale ontwikkeling met sqld
    (docker compose) is het http://db:8080.
    """
    url = os.getenv("LIBSQL_URL", "http://localhost:8080").strip().rstrip("/")
    for old, new in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
        if url.startswith(old):
            return new + url.removeprefix(old)
    return url


def _auth_headers() -> dict:
    """Bearer-token uit het Bunny dashboard; leeg bij een lokale sqld zonder auth."""
    token = os.getenv("LIBSQL_AUTH_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _encode_arg(value) -> dict:
    """Zet een Python-waarde om naar een Hrana-waarde voor query-parameters."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _decode_value(cell: dict):
    """Zet een Hrana-waarde uit een resultaat om naar een Python-waarde."""
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell["base64"])
    return cell.get("value")


async def _pipeline(sql: str, params: tuple) -> dict | None:
    """
    Voert een statement uit via Hrana-over-HTTP en geeft het ruwe resultaat
    terug (cols/rows/affected_row_count/last_insert_rowid), of None bij een
    fout of onbereikbare database.
    """
    if _client is None:
        return None
    body = {
        "requests": [
            {
                "type": "execute",
                "stmt": {"sql": sql, "args": [_encode_arg(p) for p in params]},
            },
            {"type": "close"},
        ]
    }
    try:
        response = await _client.post("/v2/pipeline", json=body)
        response.raise_for_status()
        result = response.json()["results"][0]
        if result.get("type") != "ok":
            logger.error("libSQL fout: %s", result.get("error", {}).get("message"))
            return None
        return result["response"]["result"]
    except Exception as e:
        logger.error("libSQL request mislukt: %s", e)
        return None


async def _ensure_schema() -> None:
    """Maakt de counts-tabel aan als die nog niet bestaat."""
    if await _pipeline(SCHEMA_SQL, ()) is None:
        logger.warning("Schema-controle mislukt; database mogelijk (nog) niet bereikbaar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opent de gedeelde HTTP-client bij opstart; sluit hem netjes af bij afsluiten."""
    global _client
    _client = httpx.AsyncClient(
        base_url=_base_url(),
        headers=_auth_headers(),
        timeout=httpx.Timeout(10.0),
        # Retry op verbindingsfouten: een remote database over internet heeft
        # af en toe een haperende verbinding; dit vangt dat stilletjes op.
        transport=httpx.AsyncHTTPTransport(retries=2),
    )
    await _ensure_schema()
    yield
    await _client.aclose()


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


# --- Database hulpfuncties --- Mooindag!

async def db_query(sql: str, params: tuple = ()) -> list | None:
    """
    Voert een SELECT-query uit en geeft alle rijen terug als lijst van dicts.
    Geeft None terug bij een DB-fout of onbereikbare DB.
    """
    result = await _pipeline(sql, params)
    if result is None:
        return None
    names = [col.get("name") for col in result.get("cols", [])]
    return [
        dict(zip(names, (_decode_value(cell) for cell in row)))
        for row in result.get("rows", [])
    ]


async def db_execute(sql: str, params: tuple = ()) -> bool:
    """Voert een niet-SELECT statement uit. Geeft True terug bij succes."""
    return await _pipeline(sql, params) is not None


async def db_insert(sql: str, params: tuple = ()) -> int | None:
    """Voert een INSERT uit en geeft het nieuwe rij-ID terug."""
    result = await _pipeline(sql, params)
    if result is None or result.get("last_insert_rowid") is None:
        return None
    return int(result["last_insert_rowid"])


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


async def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Sla een nieuwe count op en geef het automatisch toegewezen ID terug."""
    return await db_insert(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (?, ?, ?, ?)",
        (message, str(date), str(time), client_ip),
    )


async def get_counter(entry_id: int) -> dict | None:
    """Haal een specifieke count op via ID, of None als die niet bestaat."""
    rows = await db_query("SELECT * FROM counts WHERE id = ?", (entry_id,))
    return rows[0] if rows else None


async def get_all_counters() -> list | None:
    """Haal alle counts op, gesorteerd van nieuwste naar oudste."""
    return await db_query("SELECT id, message, date, time FROM counts ORDER BY id DESC")


async def get_latest_counter() -> int | None:
    """
    Geeft de huidige tellerstand terug: het hoogste ID in de tabel.
    Geeft 0 terug als de tabel leeg is, None als de DB niet bereikbaar is.
    """
    rows = await db_query("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if rows is None:
        return None
    return rows[0]["id"] if rows else 0


async def message_exists(message: str) -> bool:
    """Controleert of een bericht al eerder is ingevoerd (duplicaatbeveiliging)."""
    rows = await db_query("SELECT 1 FROM counts WHERE message = ? LIMIT 1", (message,))
    return bool(rows)


# --- Routes --- Mooindag...

@app.get("/")
async def index(request: Request):
    """Toont de hoofdpagina met de huidige tellerstand."""
    counter = await get_latest_counter()
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
    counter = await get_latest_counter()
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
    if await message_exists(message):
        return templates.TemplateResponse(
            request, "index.html", {"counter": counter, "error_message": "duplicate"}
        )

    new_id = await save_counter(
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
    data = await get_all_counters()
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
    rows = await db_query("SELECT 1")
    if rows is not None:
        return JSONResponse({"status": "ok", "served_by": SERVED_BY})
    return JSONResponse({"status": "db_unavailable", "served_by": SERVED_BY}, status_code=503)


# --- JSON API --- Mooindag!

@app.get("/api/counts")
async def api_counts():
    """Geeft alle counts terug als JSON-array, gesorteerd van nieuwste naar oudste."""
    counters = await get_all_counters()
    if counters is None:
        return JSONResponse({"error": "Database unavailable"}, status_code=503)
    return JSONResponse(
        [{"id": c["id"], "message": c["message"], "date": c["date"]} for c in counters]
    )


@app.get("/api/counts/{id}")
async def get_api_count(id: int):
    """Geeft een specifieke count terug als JSON op basis van ID."""
    entry = await get_counter(id)
    if not entry:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({k: v for k, v in entry.items() if k != "client_ip"})


@app.delete("/api/counts/{id}")
async def delete_api_count(id: int):
    """Verwijdert een count via de API. Geeft 503 terug als de DB niet bereikbaar is."""
    ok = await db_execute("DELETE FROM counts WHERE id = ?", (id,))
    if not ok:
        return JSONResponse({"error": "Database unavailable"}, status_code=503)
    return JSONResponse({"message": f"Record {id} deleted"})
