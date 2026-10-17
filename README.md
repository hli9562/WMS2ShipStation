# WMS2ShipStation

Local web workspace for manually exported XLWMS orders. Development is tracked in [GitHub issues](https://github.com/hli9562/WMS2ShipStation/issues).

Current checkpoint: application scaffold, migrations, persistent local storage, and health page. Label purchase is not implemented yet.

## Run with Docker

Install and start Docker Desktop (or another Docker engine with Compose v2), then:

```sh
docker compose up --build -d --wait
```

Open http://localhost:8080. No credentials or `.env` file are required for this checkpoint. Optional: copy `.env.example` to `.env` and change `PORT` if 8080 is in use. The published port binds only to your computer's loopback interface.

```sh
docker compose logs -f app
docker compose down
```

The `app_data` named volume holds `/data/app.sqlite3` and `/data/labels`. `docker compose down` preserves it; **`docker compose down -v` deletes it**. Do not use the latter for real data. The application runs as UID/GID 10001. If using your own bind mount instead of the named volume, make it writable by that user.

A fresh local single-process startup applies Alembic migrations. Repeated startup preserves existing data. Cloud deployment will run migrations separately. Secrets and private exports must never be added to Git or baked into images. Provider credentials will be connected in the ShipStation implementation issue.

## Native development

Use Python 3.12 and uv 0.13.1:

```sh
uv sync --frozen
uv run python -m wms2ship
uv run pytest -q
uv run ruff check .
```

Default data location is `./data`; override with `WMS_DATA_DIR`. Native execution binds to loopback. Container execution listens on all interfaces internally, with Compose publishing only to loopback. Do not expose the unauthenticated local mode to a LAN or the Internet.

## Backup and restore

Stop the application before copying the whole data directory/volume so the database and label files represent one checkpoint. For Docker, from the repository directory:

```sh
mkdir -p backups
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup" app python -m wms2ship.backup create /backup/checkpoint.tar.gz
docker compose start app
```

This uses SQLite's backup API and includes all labels with a checksum manifest. Backup archives contain private recipient data: keep them private and outside Git. Choose a new filename for each backup.

Restore only into an empty data volume/directory; never overwrite existing history:

```sh
docker compose stop app
docker compose run --rm --no-deps -v "$PWD/backups:/backup:ro" app python -m wms2ship.backup restore /backup/checkpoint.tar.gz
docker compose start app
```

For a rehearsal, use a separate empty Compose project/volume rather than deleting your active volume. On native Python the corresponding commands are `uv run python -m wms2ship.backup create /path/checkpoint.tar.gz` and `... restore /path/checkpoint.tar.gz` with the application stopped.

## Design documents

- [English requirements](PDR.md) / [中文需求](PDR.zh-CN.md)
- [Architecture and technology stack](docs/ARCHITECTURE.md)
- [Database design](docs/DATABASE.md)
- [Development plan](docs/DEVELOPMENT_PLAN.md)

Future hosting targets Google Cloud Run, Cloud SQL PostgreSQL, private Cloud Storage and Secret Manager. Local Docker remains supported.
