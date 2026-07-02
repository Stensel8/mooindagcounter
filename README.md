# Mooindagcounter

Mooindag! FastAPI-teller, draait op Bunny.net Magic Containers.

## Twee varianten

Deze repo bevat twee complete, onafhankelijke deployment-varianten van dezelfde
app. `web/app.py` (routes, teller-logica) en de templates zijn **identiek** in
beide mappen; het enige codeverschil is de datalaag (`web/db.py`) en verder
verschilt alleen de deployment.

| | [`microservices/`](microservices/) | [`bunny-libsql/`](bunny-libsql/) |
|---|---|---|
| Database | MariaDB (zelf gehost) | [Bunny Database](https://bunny.net/database/) (managed, libSQL) |
| Containers | web + db | alleen web |
| Volumes/state | 1 volume voor MariaDB | geen |
| Multi-region | web schaalt vrij; db op 1 plek | web schaalt vrij; reads uit replica's dichtbij |
| Draait op | docker compose, Kubernetes, Bunny (2 apps) | Bunny Magic Containers + Bunny Database |
| Kosten database | ~$4/maand (24/7 pod + anycast IP) | ~$0 (usage-based; gratis tijdens preview) |
| Status | bewezen techniek | Bunny Database is public preview |

**Keuzehulp:** wil je zelf een database beheren en/of op Kubernetes draaien
(leerzaam!), kies `microservices/`. Wil je nul beheer, de laagste kosten en
wereldwijd snelle reads, kies `bunny-libsql/`.

### Waarom dit zo opgezet is

De oorspronkelijke deployment draaide web + MariaDB samen in één Magic
Containers app. Bunny start dan per regio een pod met beide containers en
**elke pod krijgt een eigen volume**: Amsterdam en Tokyo hadden dus elk hun
eigen database (andere teller per refresh), opschalen gaf een nieuwe pod met
een lege database (teller op 0) en afschalen kon InnoDB-crash-recovery
veroorzaken. [Bunny's documentatie](https://docs.bunny.net/magic-containers/persistent-volumes)
adviseert voor databases dan ook *"run with 1 replica per volume"*. De regel
die elk containerplatform hanteert:

> **De web-laag is stateless en mag onbeperkt schalen; de database draait op
> precies 1 plek (of is een managed dienst) en iedereen verbindt daarmee.**

Beide varianten volgen deze regel, elk op hun eigen manier. Zie de README in
elke map voor het bijbehorende stappenplan.

### Welke pod bediende mij?

Elke response bevat een `X-Served-By` header (regio + pod-ID op Bunny via de
automatisch geinjecteerde `BUNNYNET_MC_REGION`/`BUNNYNET_MC_PODID` variabelen,
hostname elders) en `/healthz` geeft hem ook terug als `served_by`. Zo
controleer je met `curl -sI https://mooindagcounter.nl/` of verschillende
regio's echt dezelfde database zien.

## Routes

Identiek voor beide varianten. HTML-responses sturen `Cache-Control: no-store`
zodat CDN's en browsers niets cachen.

---

### `GET /` — Teller pagina

Toont de huidige tellerstand en het invoerformulier.

<details>
<summary>Voorbeeld</summary>

```bash
curl https://mooindagcounter.nl/
```

</details>

---

### `POST /increment` — Nieuwe count toevoegen

Formulierveld `message` is verplicht (max 300 tekens, uniek). Redirect naar `/` na opslaan.

<details>
<summary>Voorbeeld</summary>

```bash
curl -X POST https://mooindagcounter.nl/increment \
  -d "message=mooie+dag"
```

</details>

---

### `GET /overview` — Overzicht (web UI)

Tabel van alle counts, nieuwste eerst, met verwijderknop per rij.

<details>
<summary>Voorbeeld</summary>

```bash
curl https://mooindagcounter.nl/overview
```

</details>

---

### `GET /api/counts` — Alle counts (JSON)

Geeft alle counts terug als JSON-array, nieuwste eerst.

<details>
<summary>Voorbeeld</summary>

```bash
curl https://mooindagcounter.nl/api/counts
```

Respons:
```json
[
  { "id": 15, "message": "kanusje", "date": "2026-05-14" },
  { "id": 14, "message": "kanus",   "date": "2026-05-14" }
]
```

</details>

---

### `GET /api/counts/{id}` — Specifieke count (JSON)

<details>
<summary>Voorbeeld</summary>

```bash
curl https://mooindagcounter.nl/api/counts/15
```

Respons:
```json
{ "id": 15, "message": "kanusje", "date": "2026-05-14", "time": "19:58:42" }
```

</details>

---

### `DELETE /api/counts/{id}` — Count verwijderen

Verwijdert een count. De web UI (overzichtpagina) gebruikt ook dit endpoint via een `fetch`-aanroep.

<details>
<summary>Voorbeeld</summary>

```bash
curl -X DELETE https://mooindagcounter.nl/api/counts/15
```

Respons:
```json
{ "message": "Record 15 deleted" }
```

</details>

---

### `GET /healthz` — Statuscheck

Geeft `{"status": "ok"}` als de database bereikbaar is, anders HTTP 503.

<details>
<summary>Voorbeeld</summary>

```bash
curl https://mooindagcounter.nl/healthz
```

Respons:
```json
{ "status": "ok", "served_by": "DE-a1b2c3" }
```

</details>

---

### `GET /robots.txt`

Serveert `static/robots.txt` op het root-pad.

---

## Deployment

GitHub Actions bouwt en pusht drie images naar GHCR, onder de namespace van
de **repo-eigenaar** (`ghcr.io/<owner>/…`). Forks publiceren dus automatisch
naar hun eigen namespace, zonder aanpassingen:

| Image | Bron | Variant |
|---|---|---|
| `ghcr.io/<owner>/mooindag-web` | `microservices/web` | microservices |
| `ghcr.io/<owner>/mooindag-db` | `microservices/db` | microservices |
| `ghcr.io/<owner>/mooindag-libsql` | `bunny-libsql/web` | bunny-libsql |

Goed om te weten:

- **Push naar `main`** publiceert `latest` + een `sha-…` tag; via **Actions →
  Build & Push → Run workflow** kun je ook vanaf een branch bouwen (alleen
  `sha-…`, geen `latest`).
- **Eerste keer publiceren vanaf een fork?** Nieuwe GHCR-packages staan
  standaard op *private*. Bunny's "GitHub Public" registry kan ze dan niet
  pullen: zet elk package op public via GitHub → Packages →
  *Package settings* → *Change visibility*.
- De Kubernetes-manifests wijzen naar `ghcr.io/stensel8/…`; draai je vanuit
  een andere namespace, gebruik dan de `images:`-override in
  `microservices/k8s/kustomization.yaml`.

De app draait als Gunicorn+UvicornWorker (ASGI), HTTP/2 en HTTP/3 lopen via Bunny.net.
