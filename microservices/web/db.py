"""
Datalaag: MariaDB/MySQL via aiomysql.

Enige codeverschil met de bunny-libsql-variant (Bunny Database via HTTP);
web/app.py is identiek. Biedt dezelfde functies: startup/shutdown en de
domeinfuncties voor het lezen en schrijven van counts.
"""

import asyncio
import logging
import os
import ssl

import aiomysql

logger = logging.getLogger("uvicorn.error")

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS counts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    client_ip TEXT NOT NULL
)"""

_pool: aiomysql.Pool | None = None
_pool_lock = asyncio.Lock()
_schema_ready = False

# Korte, mensvriendelijke omschrijving van de laatste fout; app.py toont
# dit op de foutpagina zodat bezoekers zien wát er misgaat.
last_error: str | None = None


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _build_ssl_context() -> ssl.SSLContext | None:
    """
    TLS zodra de database remote draait (DB_SSL=true). DB_SSL_VERIFY=false
    accepteert self-signed certificaten (MariaDB-standaard): het verkeer
    blijft versleuteld, alleen de certificaatcontrole vervalt.
    """
    if not _env_flag("DB_SSL", "false"):
        return None
    context = ssl.create_default_context(cafile=os.getenv("DB_SSL_CA") or None)
    if not _env_flag("DB_SSL_VERIFY", "true"):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


async def _ensure_schema(pool: aiomysql.Pool) -> None:
    """Maakt de counts-tabel aan; wordt per request geprobeerd tot het lukt."""
    global _schema_ready
    if _schema_ready:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(SCHEMA_SQL)
        _schema_ready = True
    except Exception as e:
        logger.warning("Schema-aanmaak nog niet gelukt: %s", e)


async def _create_pool() -> aiomysql.Pool | None:
    global last_error
    try:
        pool = await aiomysql.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            db=os.getenv("DB_NAME", "mooindagcounter"),
            ssl=_build_ssl_context(),
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
            # Vernieuw idle verbindingen: firewalls/NAT tussen web en een
            # remote database sluiten stille verbindingen geruisloos af.
            pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "280")),
            autocommit=True,
            cursorclass=aiomysql.DictCursor,
            minsize=2,
            maxsize=10,
        )
    except Exception as e:
        logger.error("Kan geen databaseverbinding opzetten (%s): %s", type(e).__name__, e)
        last_error = "de database is even niet bereikbaar"
        return None
    await _ensure_schema(pool)
    return pool


async def _get_pool() -> aiomysql.Pool | None:
    """Lazy: de app blijft werken als de database trager opstart dan de webcontainer."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await _create_pool()
    return _pool


async def startup() -> None:
    await _get_pool()


async def shutdown() -> None:
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()


async def _run(sql: str, params: tuple = ()):
    """
    Voert 1 statement uit op een poolverbinding en geeft de cursor-uitkomst
    (rijen, lastrowid) terug; None bij een fout. conn.ping() herstelt een
    stilletjes verbroken verbinding, zodat de eerste request na een idle-
    periode of database-herstart geen fout geeft.
    """
    global last_error
    pool = await _get_pool()
    if pool is None:
        return None
    await _ensure_schema(pool)
    try:
        async with pool.acquire() as conn:
            await conn.ping()
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                rows = await cur.fetchall()
                last_error = None
                return {"rows": rows, "lastrowid": cur.lastrowid}
    except Exception as e:
        logger.error("Databasefout (%s): %s | sql: %s", type(e).__name__, e, sql.split()[0])
        last_error = "de database gaf een fout op deze opdracht"
        return None


# --- Domeinfuncties (identieke interface in beide varianten) --- Mooindag!

async def save_counter(message: str, date, time, client_ip: str) -> int | None:
    """Bewaart een nieuwe count; geeft het toegewezen ID terug."""
    result = await _run(
        "INSERT INTO counts (message, date, time, client_ip) VALUES (%s, %s, %s, %s)",
        (message, str(date), str(time), client_ip),
    )
    return result["lastrowid"] if result else None


async def get_counter(entry_id: int) -> dict | None:
    result = await _run("SELECT * FROM counts WHERE id = %s", (entry_id,))
    return result["rows"][0] if result and result["rows"] else None


async def get_all_counters() -> list | None:
    result = await _run("SELECT id, message, date, time FROM counts ORDER BY id DESC")
    return result["rows"] if result else None


async def get_latest_counter() -> int | None:
    """Tellerstand = hoogste ID; 0 bij lege tabel, None bij een fout."""
    result = await _run("SELECT id FROM counts ORDER BY id DESC LIMIT 1")
    if result is None:
        return None
    return result["rows"][0]["id"] if result["rows"] else 0


async def message_exists(message: str) -> bool:
    result = await _run("SELECT 1 FROM counts WHERE message = %s LIMIT 1", (message,))
    return bool(result and result["rows"])


async def delete_counter(entry_id: int) -> bool:
    return await _run("DELETE FROM counts WHERE id = %s", (entry_id,)) is not None
