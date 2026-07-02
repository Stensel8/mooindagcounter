# Microservices-variant (web + MariaDB)

Stateless web-laag die vrij mag schalen, plus **precies één**
MariaDB-instantie met een volume.

## Lokaal draaien

```bash
cp web/.env.example .env   # vul je waarden in
docker compose up --build  # app op http://localhost:8080
```

## Omgevingsvariabelen

| Variabele | Standaard | Omschrijving |
|---|---|---|
| `DB_HOST` / `DB_PORT` | `localhost` / `3306` | MariaDB adres |
| `DB_USER` / `DB_PASSWORD` | `mooindagcounter` / _(verplicht)_ | DB-login |
| `DB_NAME` | `mooindagcounter` | Databasenaam |
| `DB_SSL` | `false` | TLS; aanzetten zodra de DB niet op localhost draait |
| `DB_SSL_VERIFY` | `true` | `false` bij self-signed certificaten |
| `DB_SSL_CA` | _(leeg)_ | Eigen CA-bundel (sommige managed diensten) |
| `DB_CONNECT_TIMEOUT` | `10` | Verbindingstimeout (s) |
| `DB_POOL_RECYCLE` | `280` | Ververs idle poolverbindingen (s) |
| `DELETE_PASSWORD` | _(leeg)_ | Verwijder-wachtwoord; leeg = verwijderen uit |
| `DISCORD_WEBHOOK_URL` | _(leeg)_ | Optioneel: Discord-meldingen |
| `GUNICORN_WORKERS` | `2` | Aantal workers |

De app maakt de `counts`-tabel zelf aan (`id`, `message`, `date`, `time`,
`client_ip`); elke lege MySQL/MariaDB-database werkt. Het `mooindag-db`
image bevat daarnaast `db/create_db.sql` als init-script.

## Deployment op Bunny.net (twee Magic Container apps)

Draai web en database **nooit samen in één multi-region app** (zie de
[hoofd-README](../README.md)):

1. Nieuwe app met alleen het `mooindag-db` image: 1 regio, autoscaling
   uit (vast 1 pod), volume op `/var/lib/mysql`, endpoint op poort 3306.
2. Web-app: db-container en volume weg; `DB_HOST=<db-endpoint>`,
   `DB_SSL=true`, `DB_SSL_VERIFY=false`, een **sterk** `DB_PASSWORD`
   (de poort is publiek).
3. De web-app mag nu vrij schalen over alle regio's.

*Let op:* Bunny-volumes hebben geen backups — draai af en toe een
`mariadb-dump`, of kies de [`bunny-libsql`](../bunny-libsql/) variant.

## Kubernetes

`k8s/` bevat dezelfde architectuur als manifests: een stateless web-
[Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
(3 replicas, probes, read-only rootfs) en een MariaDB-
[StatefulSet](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
met exact 1 replica en een PersistentVolumeClaim.

```bash
kubectl create namespace mooindagcounter
kubectl -n mooindagcounter create secret generic mooindag-db \
  --from-literal=MARIADB_ROOT_PASSWORD='...' \
  --from-literal=DB_PASSWORD='...'

kubectl apply -k microservices/k8s/            # alles uitrollen
kubectl -n mooindagcounter scale deployment/web --replicas=5
```
