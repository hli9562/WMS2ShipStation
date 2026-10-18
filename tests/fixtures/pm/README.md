# Product manager test pack

These five workbooks contain synthetic recipients, addresses, products, and
order IDs. Use **Simulation** for testing. No ShipStation credentials are needed.
The files are not intended for real shipping.

## Run on your computer

1. Clone this repository, or run `git pull` in an existing checkout.
2. Install/start Docker Desktop, then run `docker compose up --build -d --wait`
   from the repository root. See the main [README](../../../README.md) for setup.
3. Open <http://localhost:8080> in Chrome or Edge.
4. In **WMS orders → Folder Monitor → Choose folder**, select this checkout's
   `tests/fixtures/pm` directory on your computer and allow read access.
   No Docker folder mount is needed. Alternatively, use the single-file picker.

Keep the app tab open and visible for automatic folder checks every 15 seconds.
Use **Refresh** for an immediate check. After reopening the browser, use
**Reconnect folder** if requested.

## Files and expected results

Expected counts assume an empty application database and the order below.

| File | Contents | Expected result |
| --- | --- | --- |
| `01-us-one-order.xlsx` | One US order, `PM-US-001`; Boston, MA; ZIP `02108`; 460 g; quantity 2 | One new order. The leading zero in the ZIP must be preserved. |
| `02-canada-one-order.xlsx` | One Canada order, `PM-CA-001`; Toronto, ON; 750 g; quantity 1 | One new order. Shipping details show Canada customs fields. |
| `03-us-three-orders.xlsx` | Three US orders, `PM-BULK-001` through `003`; 460 g, 750 g, and 1,200 g | Three new orders with quantities 1, 2, and 3. |
| `04-us-one-order-copy.xlsx` | Exact byte-for-byte copy of file 01 with a different filename | Once 01 is imported, the inbox recognizes this as imported too. A manual upload retains the existing order and reports one duplicate. |
| `05-invalid-weight.xlsx` | One order, `PM-INVALID-001`, with zero package weight | No order created; one invalid row. Inbox status becomes **Import attempted — needs review**. Click **View issues**. |

Every workbook contains the WMS `出库单` and `拣货库位明细` sheets, one SKU per
order, and one package per order. Valid package dimensions are 20 × 18.5 × 14 cm.
There are no formulas, credentials, or real customer details.

## Folder Monitor checks

- On a fresh database, all five filenames initially appear as **New**.
- Use **Select new files → Import selected**. Identical contents in files 01
  and 04 are processed once. The result is **five unique valid orders**.
- After the refresh: **4 imported files**, **1 needs review**, **0 new**.
  Completed files disappear unless **Show imported files** is checked.
- For arrival monitoring, choose an empty temporary folder, then copy files
  from this pack into it one at a time. Each appears after a check. A file
  already imported from another folder is still recognized by its contents.
- Re-importing the pack must preserve saved order edits and must not add a
  second copy of an existing order. It never creates labels automatically.

Previously imported files/order IDs remain known across restarts. For a fresh
run without deleting your existing data, create a second checkout in another
folder and start it with a different Compose project name and host port, e.g.
`docker compose -p wms-pm-fresh --env-file .env.pm up --build -d --wait`, with
`.env.pm` containing `PORT=8082`. Use <http://localhost:8082>. The separate project
has its own data volume; you can reuse it for additional tests.

## Simulated shipping and reports

1. Open any valid imported order. Choose **Simulation — no postage**, the demo
   carrier/service/package, today's ship date, timezone is derived automatically from the Katy shipper address,
   Residential or Commercial, confirmation **None**, and insurance **None**.
2. Add a synthetic shipper in **Settings**, for example contact name
   `PM Test Warehouse`, phone `555-555-0101`, street `100 Synthetic Warehouse St`,
   city `Katy`, state `TX`, ZIP `77494`, country `US`. Select it on the order.
3. For Canada, also fill customs using synthetic values: Recipient duties payer,
   Merchandise, Return to sender, item description `Synthetic test item`, unit
   value `10.00`, currency `USD`, origin `US`, and HS code `123456`.
4. **Complete shipping details → Create simulated label** (enabled automatically when ready). History
   should show **SIMULATION**, and the printable PDF must say it is not valid
   postage. Ordinary duplicate-purchase protection remains in place.
5. Open **Manager review**, filter to Simulation, and download the Excel report.
   Summary and Shipments sheets should match the filtered dashboard.

Record the filename, order ID, steps, and screenshot when reporting a problem.
