# WMS2ShipStation

Local web workspace for manually exported XLWMS orders. Development is tracked in [GitHub issues](https://github.com/hli9562/WMS2ShipStation/issues).

Current checkpoint: Docker application, migrations, XLSX import and order preview, duplicate detection, per-order configuration and readiness validation. Simulated labels and the ShipStation V1 adapter are available. Live purchasing is disabled by default.

## PM test deployment with a coding agent

Use [Test deployment and acceptance testing](docs/TEST_DEPLOYMENT.md) for a copy-and-paste Codex prompt, an isolated local workspace, and the five-XLSX acceptance checklist.

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
umask 077
set -o noclobber
mkdir -p backups
docker compose stop app
docker compose run --rm -T --no-deps app python -m wms2ship.backup create - > backups/checkpoint.tar.gz
docker compose start app
```

This uses SQLite's backup API and includes all labels with a checksum manifest. Backup archives contain private recipient data: keep them private and outside Git. Choose a new filename for each backup.

Restore only into an empty data volume/directory; never overwrite existing history:

```sh
docker compose stop app
docker compose run --rm -T --no-deps app python -m wms2ship.backup restore - < backups/checkpoint.tar.gz
docker compose start app
```

For a rehearsal, use a separate empty Compose project/volume rather than deleting your active volume. On native Python the corresponding commands are `uv run python -m wms2ship.backup create /path/checkpoint.tar.gz` and `... restore /path/checkpoint.tar.gz` with the application stopped.

## Design documents

- [English requirements](PDR.md) / [中文需求](PDR.zh-CN.md)
- [Architecture and technology stack](docs/ARCHITECTURE.md)
- [Database design](docs/DATABASE.md)
- [Development plan](docs/DEVELOPMENT_PLAN.md)

Future hosting targets Google Cloud Run, Cloud SQL PostgreSQL, private Cloud Storage and Secret Manager. Local Docker remains supported.

## Import an export

On the home page choose an `.xlsx` file and select **Import and preview**. Select an order to see recipient, package measurements and item quantity. Import summaries show new, existing and invalid orders; row issues explain what needs review. Re-imports preserve existing configuration and measurements, including when incoming values differ. Existing WMS tracking is flagged for review.

The initial parser supports a single unambiguous package and SKU per order using the documented export headers in English, Chinese, or bilingual form. Multi-package, multi-SKU and repeated picking-location mappings are blocked pending real export examples. Combined dimensions must state their unit; unitless weights are rejected. Limits: 10 MiB uploaded, 100 MiB uncompressed, 1,000 data rows/sheet, 128 columns. Identifiers must be Excel text to avoid leading-zero/precision loss. Required worksheet names are `出库单` and `拣货库位明细`. Source workbooks are parsed in memory and not retained as files. Necessary normalized row evidence is kept in the private database.

API clients send raw XLSX bytes to `POST /api/imports?filename=export.xlsx`, with `X-CSRF-Token` from the home page's meta tag; use the same origin. This endpoint does not accept multipart bodies. The order/detail APIs contain private recipient data and are intended only for the protected local workspace.

## Configure an order

Select an imported order to enter its complete Katy warehouse/contact address (also used for returns), shipping options, and applicable Canada customs information. Readiness checks run automatically as you edit. **Create label** stays disabled until the details are ready, then saves them when clicked. Missing values, incompatible carrier choices, stale edits and existing WMS tracking prevent readiness. All fields are configured per order. Without credentials the app uses simulation; configured ShipStation accounts use development test labels. Current Canada validation requires USD values, item quantity matching and a 6–10 digit HS code; duties billing is recipient-only in this initial scope. This is an application eligibility check, not address certification or legal/customs advice.

## Simulated label creation and recovery

After saving complete per-order configuration, select **Create simulated label**. The fake provider returns tracking prefixed `SIMULATED-` and a watermarked PDF; these are not usable postage. Keep simulation data separate from future live orders: the same package guards protect both simulated and live outcomes.

Purchase attempts persist before transmission. A timeout/crash becomes `uncertain` and blocks another purchase; an explicit provider rejection becomes `failed` and can be retried. A confirmed purchase with a missing PDF stays purchased and must have its existing artifact recovered. Use shipment history to open the saved original or Letter PDF; this never calls the purchase endpoint.

`GET /api/label-attempts/{id}` exposes status and events. An operator who has investigated the provider outcome may submit `POST /api/label-attempts/{id}/reconcile` with `outcome` (`confirmed_not_purchased` or `purchased`) and an evidence explanation (at least 20 characters). Confirmed purchases also require `shipment_id` and `tracking`. Only uncertain attempts are eligible; no force-purchase bypass exists. Do not include secrets in evidence. Interrupted prepared/sending attempts become uncertain on local startup.

## ShipStation account setup

Copy `.env.example` to `.env`, enter `SHIPSTATION_API_KEY` and `SHIPSTATION_API_SECRET` locally, and recreate the application container with `docker compose up -d`. Native development automatically loads `.env` from the repository when you run `uv run python -m wms2ship`. Restart the app after changing credentials. Never send credentials in chat, issues, logs, or commits.

Select ShipStation in the order form to discover connected carriers, services and package types. Discovery checks for an active Manual Store. This initial direct-label integration uses each carrier's primary account; selection of secondary accounts is not supported. International/domestic service flags filter incompatible choices; carrier-specific rules can still cause a validation rejection. WMS/platform references remain in this app and are not assumed to appear on a standalone provider label.

Leave `WMS_ENABLE_LIVE_PURCHASE=false` while reviewing and configuring. When ready for an actual paid shipment, set it to `true`, recreate the container, review the order, and explicitly confirm **Buy shipping label**. There is no automatic paid test or automatic label creation on import. The adapter calls only the V1 direct-label endpoint, not ShipStation order creation.

The implementation has been tested with HTTP mocks, not your live account. Credentials, account entitlement, carrier restrictions, returned label layout and Canadian customs output require operator acceptance. No automatic purchase retry is implemented, including after rate limiting/server errors; uncertain results require investigation.

## Print, history and artifact recovery

Shipment history includes every attempt, outcome, provider reference and tracking number, with **Load more history** for older records. Use live tracking numbers to update WMS manually. **Open Letter PDF / print** opens a stored/generated Letter copy in your browser's PDF viewer; print at **Actual size / 100%** on Letter paper. The original provider PDF is preserved unchanged. Small labels are centered without enlargement; landscape pages can rotate to fit. Oversized pages that cannot fit Letter without scaling are rejected with an instruction to review the original. Physical printer margins and barcode readability still need operator verification.

If an original PDF is missing/corrupt, restore the matching backup or download the same existing label from the provider. Do not purchase another label. `POST /api/labels/{label_id}/recover` accepts raw PDF bytes, `X-CSRF-Token`, and `X-Recovery-Evidence` (20–2000 characters). If a checksum was previously stored, recovery requires exactly the same original bytes. For purchases reconciled from an uncertain outcome without a previously saved file, the operator must verify that the recovered PDF belongs to the recorded provider shipment. Recovery only attaches a file to an existing confirmed purchase.

## Check ShipStation's official V1 documentation mock

```sh
uv run python -m scripts.check_shipstation_mock
```

This opt-in network diagnostic uses only synthetic data and dummy credentials against the fixed [official V1 mock server](https://docs.shipstation.com/apis/shipstation-v1/openapi/shipments). It does not load your `.env`, call production, create local purchase records, or change application provider settings. It checks store/carrier/service/package responses, label response fields, PDF completeness, and whether an empty label request is rejected.

On 2026-10-17 the mock returned HTTP 200 for lookups and label creation, but its store example had no Manual Store, its package example did not match the requested carrier, and `labelData` was truncated placeholder data. It is useful for API response-shape checks, not full application acceptance or printer tests. Use the app's **Simulation** provider for complete local workflow/PDF testing. An actual ShipStation developer account is a production-like account, not a guaranteed free sandbox; keep live purchase disabled until ready for an explicitly confirmed paid test.

### Saved shipper contacts

Use **Settings → Shipper contacts** to add, edit, or delete named contacts. In
**Shipping details**, select a saved contact to copy its address and phone into
the order, then save the configuration. Changes to a contact do not change
previously saved orders. Shipper and return addresses still use the Katy, TX
warehouse. Contacts are stored in the local database and included in backups;
the new table is created automatically on application startup.

### Manager shipment review and Excel reports

Open **Manager review** to review orders without labels, label purchase attempts,
tracking numbers, recorded charges, and exceptions. Filter by activity dates
(inclusive, UTC), label status, postage mode, or order/tracking/contact search.
Click **Apply filters / refresh**, then **Download Excel report** for a workbook
with Summary and Shipments sheets containing all matching records across pages.

Each record is a label attempt or an order without attempts. Rejected retries
remain visible; orders and label attempts have separate counts. Live and
simulation charges are totaled separately by currency; missing charges remain
unknown. Historical contact/carrier details come from the saved purchase
snapshot. Purchasing a label does not establish dispatch or delivery status.
The manager view uses the current shared full-access local workspace.

See [ShipStation V1 shipping options](docs/SHIPSTATION_OPTIONS.md) for the
supported choices, carrier restrictions, and official API references.

### USPS test labels with paid purchases disabled

Select **ShipStation USPS test label — not valid postage** for a dedicated
`USPS-PRIORITY-US-TEST-…` order with a US destination, Stamps.com carrier, and
no insurance or add-ons. Use **Create USPS test label** to request a V1
`testLabel: true` label. The live-purchase setting can remain false. This
mode does contact the real ShipStation API, but cannot submit `testLabel: false`.
Simulation remains the offline option. Test activity is marked `test` in
history and manager reports and is excluded from the live mode filter.
After a successful test label, click **Create another USPS test label** to run
another test on the same synthetic order. Each intentional repeat uses a fresh
request token (`repeat_test: true`) and retains prior labels and history.
Duplicate tokens return the original attempt; sending/uncertain attempts block
repeats until resolved. This exception applies only to USPS test mode and never
releases a paid-purchase guard. Do not use test labels or tracking for fulfillment.

### Folder inbox

On **WMS orders**, click **Choose folder** and allow read access to your WMS
export folder in Chrome or Edge. Top-level `.xlsx` files are checked every
15 seconds while the app is open and visible; returning to the tab refreshes
the list. Monitoring resumes after reopening the app when browser permission
is retained; otherwise click **Reconnect folder**. **Disconnect** forgets the
folder without changing its files or database history.

**Select new files → Import selected** imports only the files you select.
SHA-256 content fingerprints are compared with the database, including previous
manual uploads: renamed copies are recognized as imported, while changed content
appears new. Files with invalid order rows show **Needs review**, with a button
to view issues. **Show imported files** includes completed imports. Duplicate
contents within one selection are processed once; existing orders are preserved.

Excel lock files (`~$...`), hidden files, and nested folders are skipped. Files
newer than two seconds wait for a later check; empty, oversized (over 10 MB), or
unreadable files cannot be selected. Each selected file is checked again before
upload. The folder is read-only: monitoring never moves/deletes files or buys
postage. Folder access occurs in the browser, so no Docker host mount is needed.
Localhost and HTTPS are supported; other browsers can use the normal file picker.

## Product manager test files

Five committed synthetic XLSX files and step-by-step acceptance checks are in
[tests/fixtures/pm](tests/fixtures/pm/README.md). These tests work with Simulation
and do not require ShipStation credentials.

### History filters

**History** displays labels and attempts in a table with tracking, charges,
exceptions, and Letter/original PDF links. Search across order/platform
references, tracking, attempt/label IDs, provider, mode, status, or exception.
`*` matches any number of characters; `?` matches one character. For example,
`PM-*` matches an order prefix and `*1234` a tracking suffix. Plain text performs
a partial match; `%` and `_` are treated literally. Matching ignores ASCII case.

Use **From** and **Through** for an inclusive date/time window in your computer's
local timezone. The app converts these to timezone-aware timestamps for server
filtering. **Apply filters / refresh** starts at the first matching page;
**Load more history** uses the same filters. **Clear filters** restores all
history. Filters apply before pagination, including older records.

The shipping timezone is derived automatically from the supported Katy, TX, US
shipper address (`America/Chicago`); no timezone entry is needed.

During workflow exploration, configured ShipStation accounts use development labels
for every imported order number. The UI defaults to test mode, server saves force
that mode, and live purchases are disabled. Requests use V1 `testLabel: true`
(USPS only), including destination-appropriate international services. Test labels
can be generated repeatedly; invalid source data still needs correction.
