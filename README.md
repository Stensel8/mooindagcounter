# Mooindagcounter

Mooindag... Een teller-app. Flask + MariaDB.

## Omgevingsvariabelen

- `DB_HOST`: MariaDB host
- `DB_PORT`: MariaDB poort (standaard: `3306`)
- `DB_USER`: Database gebruiker
- `DB_PASSWORD`: Database wachtwoord (verplicht)
- `DB_NAME`: Databasenaam
- `DISCORD_WEBHOOK_URL`: Optionele Discord meldingen
- `GUNICORN_WORKERS`: Aantal app workers (standaard: `2`)

Mooindag...

## Endpoints

### Web UI
| Methode | Pad | Omschrijving |
|---------|-----|--------------|
| `GET` | `/` | Teller pagina |
| `POST` | `/increment` | Nieuwe count toevoegen |
| `GET` | `/overview` | Overzicht |
| `POST` | `/remove/<id>` | Count verwijderen |

### API (JSON)
| Methode | Pad | Omschrijving |
|---------|-----|--------------|
| `GET` | `/api/counts` | Alle counts ophalen |
| `GET` | `/api/counts/<id>` | Eén count ophalen |
| `DELETE` | `/api/counts/<id>` | Count verwijderen |
| `GET` | `/healthz` | Statuscheck |

Mooindag... Een nieuwe count toevoegen kan alleen via het webformulier.

## Structuur

- `src/web/`: Flask app
- `src/db/`: MariaDB schema
- `docker-compose.yml`: Lokale setup
- `.github/workflows/`: CI/CD

Mooindag...
