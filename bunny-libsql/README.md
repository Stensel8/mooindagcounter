# Bunny Database-variant (libSQL)

Eén stateless container met [Bunny Database](https://bunny.net/database/)
als managed datalaag — geen database-container, geen volumes, niets om te
beheren. Bunny repliceert de data naar de regio's waar je app draait.

Bunny Database spreekt het standaard libSQL/sqld-protocol (*Hrana over
HTTP*): statements als JSON naar `POST /v2/pipeline` met een Bearer-token.
Er is geen officiële Python SDK, dus `web/db.py` praat daar rechtstreeks
mee via `httpx`.

## Deployment op Bunny.net

1. Maak een database aan (dashboard → Database → Add Database); kies je
   primaire regio en voeg replica-regio's toe waar je app draait.
2. Klik op de connect-pagina op **"Add Secrets to Magic Container App"** —
   dat zet `BUNNY_DATABASE_URL` en `BUNNY_DATABASE_AUTH_TOKEN`, en die
   leest de app direct.
3. App-config: alleen het `mooindag-libsql` image, geen db-container,
   geen volume. Multi-region en autoscaling mogen vol open.

De app maakt de `counts`-tabel zelf aan; een verse, lege database is genoeg.

## Lokaal draaien

De compose start [sqld](https://github.com/tursodatabase/libsql) (de
open-source libSQL-server) als lokale vervanger van Bunny Database:

```bash
docker compose up --build   # app op http://localhost:8080
```

## Omgevingsvariabelen

| Variabele | Standaard | Omschrijving |
|---|---|---|
| `BUNNY_DATABASE_URL` | _(leeg)_ | Database-URL uit Bunny's "Add Secrets" knop, of `libsql://…` |
| `BUNNY_DATABASE_AUTH_TOKEN` | _(leeg)_ | Access token uit Bunny's "Add Secrets" knop |
| `LIBSQL_URL` / `LIBSQL_AUTH_TOKEN` | _(leeg)_ | Handmatige fallback voor URL/token |
| `DELETE_PASSWORD` | _(leeg)_ | Verwijder-wachtwoord; leeg = verwijderen uit |
| `LIVE_POLL_SECONDS` | `4` | Peil-interval voor live-updates (alleen met verbonden kijkers) |
| `DISCORD_WEBHOOK_URL` | _(leeg)_ | Optioneel: Discord-meldingen |
| `GUNICORN_WORKERS` | `2` | Aantal workers |

Tabel `counts` (SQLite-dialect, `AUTOINCREMENT` — de teller loopt nooit
terug door een delete): `id`, `message`, `date`, `time`, `client_ip`.

## Kosten & kanttekeningen

- $0.30 per **miljard** gelezen rijen, $0.30 per miljoen geschreven rijen,
  $0.10/GB per actieve regio; spint down bij inactiviteit. Voor dit project
  afgerond **$0/maand** (en gratis tijdens de public preview).
- Public preview: geen SLA. Een periodieke export
  (`curl /api/counts > backup.json`) is een prima vangnet.
