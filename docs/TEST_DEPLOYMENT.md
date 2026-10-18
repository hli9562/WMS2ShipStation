# Test deployment and acceptance testing with a coding agent

This is the entry point for Codex or another coding agent helping a product manager
run and test this repository on their own computer. Run commands from the repository
root. This guide describes the current local development workflow, not Google Cloud
or production deployment.

## Prompt the product manager can give Codex

```text
Read docs/TEST_DEPLOYMENT.md and follow it to set up a local PM test workspace.
Check the existing checkout and running services first. Preserve my existing data
and credentials. Prefer Docker and a separate Compose project on port 8082.
Help me test all five XLSX files in tests/fixtures/pm, shipping configuration,
repeated ShipStation test labels, History, and the manager report.
Create label must use development test mode only. Explain missing prerequisites
and let me enter any credentials locally; never display or commit secrets.
Guide me through browser and printer steps you cannot operate. Record what actually
passed, failed, or was not tested, and give me reproducible bug reports.
Do not change application behavior just to make a test pass.
```

## Instructions for the coding agent

1. Read this guide, `compose.yaml`, `.env.example`, and
   [the fixture manifest](../tests/fixtures/pm/README.md). Inspect Git status and
   the available runtime before changing anything. Keep unrelated local edits.
2. Check for an existing PM workspace and port conflicts. Reuse its project name,
   env file, port, and database when continuing a session. Do not kill an unrelated
   server or delete a database to obtain a clean test run.
3. Explain whether testing uses Simulation or the connected ShipStation account.
   No credentials means local Simulation. Configured V1 key/secret means ShipStation
   development labels, USPS selected by default, and every label request includes
   `testLabel: true`. There is no separate V1 development API URL. The application
   currently disables live purchasing even if the legacy enable flag is true.
4. Any valid imported order number can create a development label; no special
   `USPS-PRIORITY-US-TEST-` prefix is required. US and Canada orders can be submitted
   with destination-appropriate USPS services. Carrier rejection is a test result;
   do not claim that every service/customs combination has been verified.
5. Keep secrets in ignored local env files. Do not print `.env`, run commands that
   expand credentials into output, or attach full Compose configuration containing
   secrets. Ask the user to enter keys themselves when needed. Never commit private
   exports, database files, labels, reports, logs containing private data, or env files.
6. Preserve history and uncertain-attempt guards. Never automatically repeat an
   uncertain request, delete purchase guards, or switch to paid shipping to get a
   passing result. Completed development labels support an intentional repeat from
   the UI; the same request token remains idempotent.
7. When browser control is available, verify the UI directly. Otherwise provide
   short steps for the PM and mark those checks as awaiting user verification.
   Do not report visual or printer checks as passed based on unit tests alone.

## Preferred setup: isolated local Docker workspace

Prerequisites: Git, Docker with Compose v2, and Chrome or Edge. Docker Desktop must
be running. Verify with `git status --short`, `docker version`, and
`docker compose version`. Install missing prerequisites through the normal approved
workflow; do not silently switch to a cloud deployment.

For a new checkout:

```sh
git clone https://github.com/hli9562/WMS2ShipStation.git
cd WMS2ShipStation
```

For an existing checkout, inspect local changes before updating. Use
`git pull --ff-only` only when it will preserve the user's working tree; do not reset
or discard changes. Record the tested commit with `git rev-parse --short HEAD`.

Create `.env.pm` **only if it does not already exist**, with this content:

```dotenv
PORT=8082
SHIPSTATION_API_KEY=
SHIPSTATION_API_SECRET=
WMS_ENABLE_LIVE_PURCHASE=false
```

Leave keys empty for offline Simulation, or have the user fill their ShipStation V1
key and secret in this file locally for development labels. Do not overwrite an
existing `.env` or reuse another person's credentials. `.env.pm` is Git-ignored.
Compose interpolation also honors the shell environment; check for overrides by
variable name/presence without printing their values if the runtime differs from
this file. Use the same env file/project for every command below.

```sh
docker compose -p wms-pm --env-file .env.pm up --build -d --wait
docker compose -p wms-pm --env-file .env.pm ps
```

Open <http://localhost:8082> in Chrome or Edge and verify `/health` returns HTTP 200.
The host port binds to loopback. The project has its own persistent named volume;
restarting it preserves orders, contacts, and label history. If 8082 is occupied,
choose another unused port in `.env.pm` and report the actual URL.

The browser chooses files on the PM's computer; **no Docker host-folder mount is
needed**. Folder monitoring requires Chrome/Edge and localhost or HTTPS. It checks
while the app is open and visible. Use Reconnect folder if prompted after reopening.
The manual XLSX file picker is a fallback.

To apply changed credentials or code, run the same `up --build -d --wait` command
again. Refresh the browser afterward to get current scripts and the new CSRF token.
For troubleshooting:

```sh
docker compose -p wms-pm --env-file .env.pm logs --tail=100 app
```

Review logs privately and redact secrets/private customer data before sharing.
To stop without deleting history:

```sh
docker compose -p wms-pm --env-file .env.pm down
```

Do not use `down -v`. For another clean run, choose a new project name, such as
`wms-pm-round2`, and another unused port. Keep the old workspace intact. Follow
[backup instructions](../README.md#backup-and-restore) when a checkpoint is needed,
substituting this guide's project/env-file options in all Compose commands.

## Native fallback

If Docker is unavailable, use the repository's Python 3.12 and uv 0.13.1 setup:

```sh
uv sync --frozen
PORT=8082 WMS_DATA_DIR=data/pm-test uv run python -m wms2ship
```

This foreground command is for macOS/Linux shells. On PowerShell, set `$env:PORT`
and `$env:WMS_DATA_DIR` before `uv run python -m wms2ship`. Native startup reads
`.env`, **not `.env.pm`**. Inspect credential presence without displaying values and
agree which test mode to use before starting. Keep data under `data/pm-test` separate
from other workspaces. Stop only the process started for this task. Report the PID,
port, data directory, and exact restart command to the PM.

## Acceptance checklist

Record Pass / Fail / Not tested and evidence for each row. Counts below assume a
fresh isolated database; do not clear an existing workspace to match them.

| Check | Expected result |
| --- | --- |
| Startup | Health 200; five workspace tabs; no startup/migration errors. |
| Folder inbox | Choose `tests/fixtures/pm` in the local checkout. Five files initially appear. Changes appear after Refresh or a visible-tab check within about 15 seconds. |
| Import all five | Five unique valid orders in total. Files 01/04 are duplicate contents and process once. File 05 creates no order and shows an invalid-weight issue. After refresh: four imported files, one needs review, zero new. |
| Repeat imports | No additional orders; existing edits/history retained. Imported files can be shown using Show imported files. |
| Order list | Newest imports first, searchable order/reference, highlighted rows with no label attempts, and a working no-label-attempt filter. Order links open Shipping details. |
| Shipper contacts | Settings can add a Katy, TX, US shipper; selecting it fills the return address. No manual timezone entry. |
| Readiness | No Save configuration / Check readiness buttons. Create label stays disabled for missing or invalid details, explains problems, and enables after valid choices. Changing a ready field to an invalid value disables it again. |
| US label | USPS defaults with credentials. Choose a service, package, ship date, address type, confirmation, and insurance None. Create label produces TEST history and opens History automatically. No special order-name prefix is needed. Without credentials this check uses Simulation and produces SIMULATION history. |
| Repeat test label | Reopen the same order, create another completed development label; History retains both attempts. Do not expect repeated Simulation labels for the same package. |
| Canada | Customs fields appear. Enter recipient-paid duties, contents, non-delivery choice, matching quantity, description, positive USD value, origin country, and 6–10 digit HS code. Choose an international USPS service. Record actual carrier acceptance/rejection. |
| History | Table includes tracking/status/PDF links. Try `PM-*`, `*001`, `PM-BULK-00?`, and a date/time window covering the test. Clear filters restores rows. Reprinting creates no new attempt. |
| PDF/print | Open Letter PDF; verify test/simulation marking, Letter paper, 100% print scale. PM checks physical output on the local printer. Test labels must not be used for shipping or entered into WMS as live tracking. |
| Manager review | Filters work; exported XLSX Summary/Shipments agree with the matching dashboard records and label modes. |
| Persistence | Restart the same project; orders, shipper contacts, history and PDFs remain. Refresh browser and reconnect the folder if prompted. |
| Layout | At the PM's actual screen size, order list is easy to reach and the Create label action is visible near the top. Narrow windows stack sections without inaccessible controls. |

For account-backed tests, use a real configured shipper address acceptable to the
carrier and the repository's synthetic recipient fixtures. Missing address or
customs data must be corrected visibly; do not silently invent data to pass a test.
See the [fixture guide](../tests/fixtures/pm/README.md) for specific workbook values.

## Troubleshooting

| Symptom | Agent action |
| --- | --- |
| Choose folder disabled | Check Chrome/Edge, localhost/HTTPS, and whether a scan/import is running. Use the manual file picker if folder APIs are unavailable. |
| Demo shipping options only | Check which port/project is open and credential presence in the active env file. Recreate that project's container, refresh the page, and inspect `/api/providers`. Never display the key/secret. |
| Readiness button remains disabled | Read the displayed field errors. Check shipper, date, service/package, address type, insurance/confirmation, existing tracking, and Canada declarations. |
| 403 after restart | Refresh the browser to obtain the current CSRF token. |
| 422 | Capture the failing endpoint and response `detail`, redacted as needed. Distinguish draft validation, order validation, and carrier rejection; don't guess from HTTP status alone. |
| ShipStation lookup fails / 429 | Record endpoint/status and check account access; respect cooldown. Do not hammer refresh or repeat label POSTs. |
| Uncertain attempt / missing PDF | Preserve state and investigate the existing attempt. Do not delete data or create a replacement label automatically. |

## Automated checks and test handoff

Run automated checks separately from the PM's database. Unit tests must not load the
PM's credentials or make account-backed purchases. In a macOS/Linux shell:

```sh
SHIPSTATION_API_KEY= SHIPSTATION_API_SECRET= uv run pytest -q
uv run ruff check .
```

On PowerShell, run tests in an isolated checkout without `.env` and without
ShipStation credential environment variables in that test process. Avoid supplying
dummy credentials globally: credential presence changes application mode. Restore
the prior shell environment afterward.
Do not run `scripts/smoke.py` against the PM workspace; it inserts its own data and
is intended for a disposable CI app.

Give the PM a handoff containing:

- Tested commit, runtime, project/port/URL, browser, and data location.
- Current mode: Simulation or account-backed ShipStation TEST; no live purchase.
- Checklist outcomes, actual counts, and which checks need the PM or printer.
- Each bug's filename/order ID, steps, expected/actual result, redacted endpoint
  response, screenshot if available, and whether a label attempt was created.
- Restart/stop commands and preserved-data location; no secrets in the handoff.

Do not create external issues or send reports unless the user asks. If asked to fix
a bug, preserve the failing evidence, make a focused change, and rerun relevant checks.
