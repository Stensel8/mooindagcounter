"""
Datalaag: MariaDB/MySQL via aiomysql.

Dit bestand is het enige codeverschil tussen de twee varianten in deze repo:
web/app.py is identiek, alleen de datalaag (web/db.py) verschilt. Beide
varianten bieden dezelfde functies aan: startup/shutdown/ping en de
domeinfuncties voor het lezen en schrijven van counts.
"""

import asyncio
import logging
import os
import ssl

import aiomysql

logger = logging.getLogger("uvicorn.error")

# Schema wordt door de app zelf aangemaakt als het nog niet bestaat.
# Hierdoor werkt de app tegen elke lege MySQL/MariaDB-database (managed
# database of los gehoste MariaDB) zonder het aparte db-image met init-script.
SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""

# Globale verbindingspool; gedeeld tussen alle requests.
_pool: aiomysql.Pool | None = None
_pool_lock = asyncio.Lock()

# Of de counts-tabel bevestigd bestaat. Zolang dat niet zo is, wordt de
# CREATE TABLE bij elk request opnieuw geprobeerd, zodat een database die
# trager opstart dan de webcontainer alsnog zijn schema krijgt.
_schema_ready = False


def _env_flag(name: str, default: str) -> bool:
    """Leest een boolean omgevingsvariabele ('true', '1', 'yes', 'on')."""
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _build_ssl_context() -> ssl.SSLContext | None:
    """
    Bouwt een TLS-context voor de databaseverbinding (DB_SSL=true).
    Nodig zodra de database niet meer als sidecar op localhost draait maar
    remote: het verkeer gaat dan over het publieke internet en moet
    versleuteld zijn. Zet DB_SSL_VERIFY=false bij self-signed certificaten
    (zoals MariaDB standaard zelf genereert): het verkeer blijft versleuteld,
    alleen de servercertificaat-controle vervalt. Met DB_SSL_CA kan een eigen
    CA-bundel worden opgegeven (vereist door o.a. managed MySQL-diensten).
    """
    if not _env_flag("DB_SSL", "false"):
        return None
    context = ssl.create_default_context(cafile=os.getenv("DB_SSL_CA") or None)
    if not _env_flag("DB_SSL_VERIFY", "true"):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def _ensure_schema(pool: aiomysql.Pool) -> None:
    """Maakt de counts-tabel aan als die nog niet bestaat (eenmalig bij succes)."""
    global _schema_ready
    if _schema_ready:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(SCHEMA_SQL)
        _schema_ready = True
    except Exception as e:
        logger.warning("Schema-controle mislukt: %s", e)


async def _create_pool() -> aiomysql.Pool | None:
    """Maakt de verbindingspool aan. Geeft None terug als de DB niet bereikbaar is."""
    try:
        pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            db=os.getenv("DB_NAME", "mooindagcounter"),
            ssl=_build_ssl_context(),
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
            # Vernieuw idle verbindingen periodiek: firewalls en NAT tussen de
            # webcontainer en een remote database sluiten stille verbindingen
            # geruisloos af, wat anders sporadische query-fouten geeft.
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "280")),
            autocommit=True,
            cursorclass=aiomysql.DictCursor,
            minsize=2,
            maxsize=10,
        )
    except Exception as e:
        logger.warning("DB-pool aanmaken mislukt: %s", e)
        return None
    await _ensure_schema(pool)
    return pool


async def _get_pool() -> aiomysql.Pool | None:
    """
    Geeft de verbindingspool terug, of maakt hem aan als die er nog niet is.
    Lazy initialisatie zodat de app blijft werken als de DB trager opstart
    dan de webcontainer (o.a. bij Bunny Magic Containers met gedeelde namespace).
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await _create_pool()
    return _pool


async def startup() -> None:
    """Probeert de pool bij opstart alvast aan te maken (lazy retry per request)."""
    await _get_pool()


async def shutdown() -> None:
    """Sluit de pool netjes af bij het stoppen van de applicatie."""
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()


async def _query(sql: str, params: tuple = ()) -> list | None:
    """
    Voert een SELECT-query uit en geeft alle rijen terug als lijst van dicts.
    Geeft None terug bij een DB-fout of onbereikbare DB.
    """
    pool = await _get_pool()
    if pool is None:
        return None
    await _ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            # Herstelt een stilletjes verbroken verbinding (reconnect=True is
            # standaard) voordat de query draait; voorkomt een eenmalige 503
            # na een idle-periode of een herstart van de database.
            await conn.ping()
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()
    except Exception as e:
        logger.error("DB query fout: %s", e)
        return None


async def _execute(sql: str, params: tuple = ()) -> bool:
    """Voert een niet-SELECT statement uit. Geeft True terug bij succes."""
    pool = await _get_pool()
    if pool is None:
        return False
    await _ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            await conn.ping()
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
        return True
    except Exception as e:
        logger.error("DB execute fout: %s", e)
        return False


async def _insert(sql: str, params: tuple = ()) -> int | None:
    """Voert een INSERT uit en geeft het nieuwe rij-ID terug."""
    pool = await _get_pool()
    if pool is None:
        return None
    await _ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            await conn.ping()
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return cur.lastrowid
    except Exception as e:
        logger.error("DB insert fout: %s", e)
        return None


# --- Domeinfuncties (identieke interface in beide varianten) --- Mooindag!

async def ping() -> bool:
    """Controleert of de database bereikbaar is (voor /healthz)."""
    return await _query("SELECT 1") is not None


async def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Sla een nieuwe count op en geef het automatisch toegewezen ID terug."""
    return await _insert(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (%s, %s, %s, %s)",
        (message, str(date), str(time), client_ip),
    )


async def get_counter(entry_id: int) -> dict | None:
    """Haal een specifieke count op via ID, of None als die niet bestaat."""
    rows = await _query("SELECT * FROM counts WHERE id = %s", (entry_id,))
    return rows[0] if rows else None


async def get_all_counters() -> list | None:
    """Haal alle counts op, gesorteerd van nieuwste naar oudste."""
    return await _query("SELECT id, message, date, time FROM counts ORDER BY id DESC")


async def get_latest_counter() -> int | None:
    """
    Geeft de huidige tellerstand terug: het hoogste ID in de tabel.
    Geeft 0 terug als de tabel leeg is, None als de DB niet bereikbaar is.
    """
    rows = await _query("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if rows is None:
        return None
    return rows[0]["id"] if rows else 0


async def message_exists(message: str) -> bool:
    """Controleert of een bericht al eerder is ingevoerd (duplicaatbeveiliging)."""
    rows = await _query("SELECT 1 FROM counts WHERE message = %s LIMIT 1", (message,))
    return bool(rows)


async def delete_counter(entry_id: int) -> bool:
    """Verwijdert een count. Geeft True terug bij succes."""
    return await _execute("DELETE FROM counts WHERE id = %s", (entry_id,))
