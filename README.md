# WMS2ShipStation

Local web workspace for manually exported XLWMS orders. Development is tracked in [GitHub issues](https://github.com/hli9562/WMS2ShipStation/issues).

Current checkpoint: Docker application, migrations, XLSX import and order preview, duplicate detection, per-order configuration and readiness validation. Simulated labels and the ShipStation V1 adapter are available. Live purchasing is disabled by default.

## PM test deployment with a coding agent

Use [Test deployment and acceptance testing](docs/TEST_DEPLOYMENT.md) for a copy-and-paste Codex prompt, an isolated local workspace, and the five-XLSX acceptance checklist.

## Employee onboarding tutorial

The Chinese employee guide includes numbered screenshots, WMS export/import steps,
US package units, confirmed purchases, thermal printing, tracking entry, and
troubleshooting. WMS export/tracking-entry menus and the shared folder location
are marked for supervisor confirmation. Screenshots use synthetic training data.

- [Markdown guide](output/pdf/onboarding/WMS2ShipStation_新员工操作手册.md)
- [Printable PDF](output/pdf/onboarding/WMS2ShipStation_新员工操作手册.pdf)

## Run with Docker

Install and start Docker Desktop (or another Docker engine with Compose v2), then:

```sh
docker compose up --build -d --wait
```

Open http://localhost:8080. No credentials or `.env` file are required for this checkpoint. Optional: copy `.env.example` to `.env` and change `PORT` if 8080 is in use. The published port binds only to your computer's loopback interface.

To share with coworkers on the same LAN, set `WMS_BIND_ADDRESS=0.0.0.0` in your local env file and add the host computer's LAN IP to `WMS_ALLOWED_HOSTS`, for example `WMS_ALLOWED_HOSTS='["localhost","127.0.0.1","192.168.86.46"]'`. Recreate the container, then open `http://<host-LAN-IP>:<PORT>` on the other computer. All users share the host's data, and the host must remain awake. This provides access without a login to devices that can reach the port. Folder Monitor requires a browser secure context (localhost or HTTPS); use manual XLSX upload when connecting over LAN HTTP.

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

Shipment history includes every attempt, outcome, provider reference and tracking number, with **Load more history** for older records. Use live tracking numbers to update WMS manually. **Label PDF / thermal print** opens the unchanged original provider PDF, which is also the default PDF endpoint output. For 4 × 6 inch thermal stock, select matching paper, **Actual size / 100%**, and no margins in the print dialog. The app adds no surrounding Letter page or white border. Carrier artwork and barcode quiet zones are preserved. **Letter PDF (office printer)** remains available for Letter paper and centers the original without enlargement. Physical printer margins and barcode readability still need operator verification.

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

### Workspace settings

**Settings** now contains ShipStation connection management, default shipping
preferences, reusable package templates, and the existing shipper contacts.

- **Test connection** makes read-only V1 carrier and shipment requests. Blank key
  fields test the current credentials. **Save and connect** verifies both entered
  credentials before replacing the connection; failed tests preserve existing
  credentials. Changes apply without restarting and never enable paid purchasing.
  The server's `WMS_ENABLE_LIVE_PURCHASE` flag and per-purchase confirmation still apply.
- Verified credentials saved in Settings take precedence over env credentials on
  restart. They live in `WMS_DATA_DIR/shipstation_credentials.json` (mode 0600) and
  are never returned by the settings API or populated into browser fields. This
  local credential file is excluded from Git and normal data backups; re-enter
  credentials separately when restoring on another machine.
- **Default shipping settings** supply carrier/service/package choices,
  residential address type, insurance, and confirmation for orders without saved
  shipping settings. Load carrier choices from the connected account, then save.
  Existing configured orders and imported measurements are not overwritten.
- **Package templates** store named length/width/height presets, rounded up to
  whole inches. Choose a template in Shipping details to fill dimensions; actual
  weight stays unchanged. Orders retain their own dimensions when a template is
  edited or deleted. Preferences and templates are stored in SQLite and included
  in normal data backups. Migration 0007 adds their tables without altering orders.

### Legacy shipment review API

The Manager review tab has been removed. Existing records and the read-only
`/api/review` and `/api/review/report.xlsx` endpoints remain available for
compatibility. Use **History** for local label activity and **Carrier Fee Summary**
for account-wide shipping fees and customer billing exports.

Each record is a label attempt or an order without attempts. Rejected retries
remain visible; orders and label attempts have separate counts. Live and
simulation charges are totaled separately by currency; missing charges remain
unknown. Historical contact/carrier details come from the saved purchase
snapshot. Purchasing a label does not establish dispatch or delivery status.
These endpoints use the current shared full-access local workspace.

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

### Folder Monitor

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
exceptions, and thermal/Letter/original PDF links. The thermal print and Letter
versions add `Platform Reference Number: <Platform reference>` in verified blank space at the bottom
of each page, without resizing the carrier artwork or barcodes. Existing labels
also receive the platform reference on reprint; no new postage is purchased.
A missing or blank platform reference is displayed as `N/A`. If the platform
reference is too long or there is no safe blank area, printing returns an error and
the **Original carrier PDF** link remains available. The original PDF is stored
unchanged. This is a local print annotation, not a ShipStation account message setting.
Search across order/platform
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

With configured ShipStation credentials, `WMS_ENABLE_LIVE_PURCHASE=false` selects
development labels (`testLabel: true`) for imported orders. Setting it to `true`
and recreating the server selects the paid ShipStation V1 create-label API
(`testLabel: false`). The button changes to **Buy shipping label** and asks for
confirmation before each purchase. Test labels can be repeated intentionally;
paid labels retain duplicate-purchase guards. Existing history keeps its original
mode, and importing files never buys labels automatically.

In Settings, mark a saved contact as the default shipper. A single saved contact
is used automatically. The default fills orders with no shipper details; existing
order addresses and manual edits stay intact.

For orders without a saved ship date, Shipping details defaults to today in Katy
(`America/Chicago`) before 5 p.m.; at 5 p.m. or later it advances to the next
Monday–Friday. Weekend dates advance to Monday. Holidays are not excluded. The
date remains editable, and previously saved dates are preserved.


Imported package measurements are automatically converted to ounces and inches
for shipping forms and the imported-data preview. Metric source values remain
available internally for compatibility. Import accepts cm/mm/in dimensions and
kg/g/lb/oz weight; weight and each dimension are rounded up to whole oz/in values after conversion.
The same whole numbers are used in shipping forms and carrier requests. Older imported orders also
display converted US measurements when opened.

## Carrier Fee Summary

The **Carrier Fee Summary** tab appears immediately before **Settings** and reads
**the entire connected ShipStation account**, including labels purchased on the
ShipStation website. It does not depend on orders imported into this app.
Choose inclusive **From** and **Through** ship dates (the dates returned by
ShipStation); the default is the current month through today.

The page and Excel statement show **Order #**, **Tracking #**, **Recipient**,
**Carrier**, and **Shipping Fee (USD)**. The **Carrier** cell displays the carrier with the specific shipping service on
the next line (for example, **USPS Ground Advantage** or **UPS 2nd Day Air**),
in both the webpage and Excel. API display names are preferred when supplied;
otherwise codes are formatted into readable names. Excel has one sheet,
**Shipping Fees**, and a final **TOTAL** row. Fees equal `shipmentCost` plus
`insuranceCost`, summed in integer cents. Missing fees are blank and totals are
explicitly marked incomplete. ShipStation-voided shipments are excluded.
ShipStation's API excludes externally fulfilled orders without a ShipStation label;
subsequent carrier billing adjustments are not included in the reported charges.

This read-only integration calls V1 `GET /shipments` with `shipDateStart` and
`shipDateEnd`. It reads all API pages, deduplicates shipment IDs, and rejects
partial/changing datasets or ranges beyond the API's 10,000-result limit. Choose
a shorter range for larger reports. A complete result is cached for 60 seconds
so on-screen pagination and Excel can reuse it. No local shipping data is changed,
and the report cannot purchase labels. Authentication, rate-limit, and API failures
show explicit errors instead of a zero-dollar statement or partial total.

The server needs active **V1 API Key and API Secret** credentials with account API
access. Being logged into ShipStation in a browser does not authenticate this API.
HTTP 401/403 requires checking credentials and account access in ShipStation's
API Settings; credentials are configured locally in the server's env file.

## Manually remove a local label

In **History** or **Shipment review**, click **Remove label** and confirm.
This only retires the label in WMS2ShipStation. It never contacts ShipStation,
cancels postage, or requests a refund. Cancel unused paid postage separately in
ShipStation if needed.

Removed labels retain their local purchase history and original charge. Their
PDF links are disabled and their purchase guard is released, so a replacement
can be created manually. Existing downloaded or printed copies remain unchanged.

New workspaces include Apex Tech / Apex Technology Distribution Inc,
20436 Westfield Commerce Dr, Katy, TX 77494, US as the default shipper contact.
No phone number is prefilled. Existing contacts/defaults are preserved on upgrade;
the seeded contact remains editable in Settings and is not recreated after deletion.

### Order search and batch printing

WMS orders searches order number, platform reference, recipient name and tracking number across
all imported orders. Status filters and 100-row pages help narrow the list. Selection resets
when changing the search, status or page. Select up to 100 printable labels on the current page,
choose **Open selected labels**, then open the generated PDF link. Print on 4 × 6 inch paper at
Actual size / 100%, with no margins. This combines existing labels without buying postage;
simulation and test labels remain invalid for shipping. Removed or unavailable labels fail the
whole batch with an error instead of silently omitting pages. Each page retains its Platform
Reference Number. The footer shows the release version and date for comparing employee installs.

### Compare Rates before purchasing

In Shipping details, complete the package measurements, address type and delivery confirmation,
then choose **Compare Rates**. Standard parcel compares the `package` type on the connected primary
carrier accounts; carriers without that compatible package are listed as unavailable. For carrier
boxes or Flat Rate packaging, select the carrier/package in Shipping options and use **Selected
carrier and package type**. USPS test mode only compares USPS services.

The table sorts the returned shipment cost plus `otherCost`, in USD, and marks the lowest returned
estimate. Select a row to fill Carrier, Service and Package type. The live purchase button then
shows the estimate; normal purchase validation must also pass. Edits to the draft or comparison
scope invalidate quotes, as does five minutes elapsed. The UI requires a current selected quote
before a live purchase. The existing purchase API and duplicate-purchase guards are unchanged.

Rate lookup uses ShipStation V1 `/shipments/getrates`; it does not save the order or buy postage.
Insurance, selected add-ons, duties/taxes, ship-date-specific pricing and later carrier adjustments
are not included in the estimate. This endpoint does not supply delivery estimates. Actual charges
are recorded after purchase. Carrier quote errors remain visible beside successful results;
missing or invalid prices are never presented as zero. Authentication errors require active V1
credentials and API account access. Documentation:
https://www.shipstation.com/docs/api/shipments/get-rates/

Rate comparison uses ShipStation V1 `/shipments/getrates` for every connected
carrier, including when label creation is in test mode. Leaving `serviceCode` empty
requests all services returned for the shipment and package. Standard parcel compares
all carriers with a compatible `package` type; selected carrier/package supports
other packaging. Quotes do not create labels or purchase postage. Unsupported
services, missing compatible packaging, and carrier errors may limit returned quotes.

Shipping follows three steps: basic shipper/package/delivery details, Get Quotes
and service selection, then final review and purchase. Quote selection fills the
carrier/service/package and shows both addresses, ship date, measurements, and the
estimated price. A current selected quote is required for account-backed test and
live labels; changing shipment details or quote expiry requires a fresh comparison.
Simulation remains available without a connected account.

Quotes appear as selectable service cards grouped by carrier, with locally stored
carrier logos and color accents. Carrier groups are ordered by their lowest quote,
and services within each group by price. The lowest returned price is marked;
selection updates the final shipment review without purchasing postage.
