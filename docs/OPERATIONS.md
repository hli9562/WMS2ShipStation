# Local test version — operator guide

Updated: 2026-10-17. This is a test candidate; live account and physical printer acceptance remain pending.

## Start and test without postage

1. Install/start Docker Desktop or another Docker engine with Compose v2. On the current development Mac, Docker was not installed; container checks ran in GitHub Actions instead.
2. From the repository, run `docker compose up --build -d --wait`, then open http://localhost:8080. No ShipStation credentials are needed for simulation.
3. Download the synthetic US test export linked on the home page, then import it. It contains fictional data and must never be used for real shipping. Re-importing it should report an existing order.
4. Select the order. Fill in warehouse/contact information for Katy, TX, US; it is also the return address. Choose **Simulation**, demo carrier/service/package, a ship date, timezone, address type, confirmation, and insurance. Select **Check readiness** and resolve the listed fields.
5. Select **Create simulated label**. History should show `SIMULATION`, a purchased simulated attempt, and a tracking number beginning `SIMULATED-`. These are not valid postage or WMS shipping results.
6. Open the Letter PDF. Check the simulation watermark, Letter paper size, and print at Actual size / 100%. Reopen/reprint from history; it must not create another attempt.
7. Restart with `docker compose down` followed by `docker compose up -d --wait`. Confirm the order, history and PDF remain available. Never use `down -v` on data you need.

For a synthetic Canada workbook, run `docker compose exec -T app python -m wms2ship.sample --country CA > synthetic-canada.xlsx` and import it. Enter the actual origin/description/HS/unit-value fields only when preparing a real order; use clearly fictional declarations in simulation. Canadian quantities must match imported items; this initial V1 mapping uses USD and recipient-paid duties.

Use a separate fresh data volume for live operation. Simulated purchases intentionally retain the same package guards as live purchases; there is no bypass that silently resets an order for another purchase. A simulation workspace is not a source of usable postage.

## Connect the real account

Configure credentials only in your local `.env` following the [README](../README.md#shipstation-account-setup). They are never entered in the browser. With live purchase disabled, select ShipStation to check the active Manual Store and connected primary carrier accounts, services and packages.

Before enabling paid purchases, use a real WMS export and review all recipient, origin, package, shipping and applicable customs information. The app does not certify address deliverability or infer missing declarations. Unsupported/ambiguous exports should be corrected in WMS or reviewed before use.

Set `WMS_ENABLE_LIVE_PURCHASE=true` and recreate the container only when ready to buy a label. Selecting **Buy shipping label** requires explicit confirmation and can charge the carrier account. Development tests did not buy postage or call your live account. No automated test depends on real credentials.

Verify the first actual label against the chosen service, package measurements, recipient, shipping origin, tracking result, Letter layout and applicable customs documents. Print it and verify the barcode with your normal scanning workflow. Manually enter only the verified live tracking number into WMS.

## When something fails

| Outcome | Operator action |
| --- | --- |
| Import/validation error | Read the sheet/row/field error and fix the input/configuration. No postage was bought by import. |
| Confirmed provider rejection (`failed`) | Correct the configuration; a new explicitly confirmed attempt may be made. |
| `uncertain` or interrupted attempt | Investigate the provider portal/support. Do not buy again or switch providers to work around the guard. |
| Purchased, PDF missing | Recover the same existing provider label or restore a backup. Do not buy another. |
| Existing WMS tracking | Investigate the existing shipment; purchase is blocked. |
| Stale configuration | Reload the order and review changes before saving/purchasing. |

History displays attempt IDs for investigation. API-based reconciliation and PDF recovery are documented in the [README](../README.md#simulated-label-creation-and-recovery); user-facing recovery forms are a follow-up usability improvement. Record provider evidence without including secrets. An immediate empty provider search is not proof that a purchase failed.

## Back up before real use

Follow [backup/restore instructions](../README.md#backup-and-restore) with the app stopped. Streaming the archive through Compose avoids host-directory ownership problems with the non-root container. Keep archives private, use a new filename each time, and rehearse restoration into an empty separate volume before relying on backups. Restore refuses a populated data directory.

No automatic history deletion or label void/replacement is provided. Do not expose this unauthenticated local workspace to a LAN or the Internet. Google Cloud hosting will require the separate authenticated deployment/migration phase.

## Acceptance still requiring the operator

- [ ] Docker starts on the actual workstation and the workflow is usable there.
- [ ] Warehouse/contact details, connected carrier accounts and services are correct.
- [ ] Actual printer produces a readable label at the correct physical size; verify barcode readability using normal operations.
- [ ] Canadian customs configuration and provider output are checked for a representative real shipment.
- [ ] Optional: one explicitly initiated paid label is verified and its tracking manually recorded in WMS.
- [ ] Backup restoration is rehearsed for the operator's actual storage setup.

Track findings in [issue #7](https://github.com/hli9562/WMS2ShipStation/issues/7). Do not paste recipient addresses or credentials into GitHub.

### ShipStation lookup troubleshooting

Carrier/store/service/package GET responses are cached in memory for five minutes
and shared by live and USPS test modes for the same account. Restart the app to
refresh immediately after changing carrier connections. USPS test mode fetches
only Stamps.com services/packages. HTTP 429 starts a temporary lookup cooldown;
follow the wait time shown by the app. HTTP 401/403 errors indicate credentials
or account permissions; endpoint/status errors and timeouts are shown without
provider bodies or secrets. Label POST requests are never cached or retried.
