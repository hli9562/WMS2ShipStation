# Development plan — first local test release

Updated: 2026-10-17. Status: ready for implementation planning; application code has not started.

References: [requirements](../PDR.md), [architecture and stack](ARCHITECTURE.md), [database](DATABASE.md).

## Release goal

Deliver a local Docker web app that imports manually downloaded WMS XLSX files, previews orders, collects warehouse/shipping/customs configuration per order, creates labels directly through ShipStation V1, prints Letter PDFs, and retains tracking/history for manual WMS entry. One Katy warehouse, US/Canada destinations, full local user access, and fewer than 100 orders/day are the initial boundaries.

The first release supports unambiguous single-package orders. Ambiguous multi-package/multi-location input is blocked rather than guessed. A provider interface is required, but only ShipStation is implemented. No WMS API, cloud deployment, automatic void/replacement, silent printing, rate comparison, or full imported-field editor is included in the estimate. Per-order forms required to complete a shipment are included.

## Work breakdown

| Work item | Depends on | Focused engineering hours |
| --- | --- | --- |
| DEV-01 Docker scaffold, persistence, migrations, CI | — | 4–6 |
| DEV-02 XLSX import, preview, provenance, duplicates | DEV-01 | 6–10 |
| DEV-03 Per-order configuration and validation | DEV-02 | 6–10 |
| DEV-04 Purchase coordinator, guards, recovery, fake provider | DEV-01, DEV-03 | 8–12 |
| DEV-05 ShipStation V1 adapter and account discovery | DEV-04 | 6–10 |
| DEV-06 Letter PDFs, printing, history, tracking | DEV-05 | 4–6 |
| DEV-07 Docker end-to-end acceptance, restore, operator guide | DEV-02 through DEV-06 | 6–10 |
| **Base estimate** | | **40–64** |
| **Planning allowance (25%)** | Integration/debugging and feedback | **10–16** |
| **First test release estimate** | | **50–80 hours** |

These are rough effort estimates, not a delivery commitment or an estimate of uninterrupted agent runtime. With one developer contributing about eight focused hours per working day and prompt operator feedback, budget approximately 7–10 working days (roughly 1½–2 working weeks) from implementation start. No calendar delivery date is committed. Re-estimate after the first import slice and provider contract check.

## Testable checkpoints

1. **Import preview:** after DEV-01/02, approximately 10–16 base hours. Operator can start Docker, import a workbook, inspect normalized data and duplicate warnings. No real label purchases.
2. **Safe simulated workflow:** after DEV-03/04, approximately 24–38 cumulative base hours. Configure per-order data and exercise success, failure, uncertain results, and duplicate protection using a fake provider. This is suitable for early workflow feedback.
3. **First ShipStation-enabled test release:** after DEV-05/06/07 and planning allowance, approximately 50–80 total hours. Includes stored Letter PDFs, history, recovery checks and setup instructions. An actual paid-label check is a separate explicit operator action.

Mock-mode UI must clearly identify simulated results. Fake labels and tracking numbers must never be presented as usable postage.

## Acceptance gate

- Docker starts with one documented command; data survives container recreation.
- Sample-equivalent imports have correct units, quantities and provenance; repeat imports do not duplicate purchases.
- Required warehouse/contact, shipping and applicable Canadian declaration fields are configured per order and validated before purchase.
- No upload or preview buys postage. Only explicit Create label initiates a purchase.
- Double clicks/concurrent requests are blocked; ambiguous purchases remain blocked until evidence-backed reconciliation.
- Success persists provider references and tracking; missing PDFs do not trigger another purchase.
- Original/Letter PDFs can be downloaded and reprinted without a purchase call; actual print/barcode readability is verified on the user's printer.
- History and artifacts can be backed up and restored. No credentials or real recipient fixtures are committed.

## Inputs and uncertainties

Development can begin with synthetic fixtures and mocked provider responses. Before live acceptance, the operator needs Docker available, server-side ShipStation V1 credentials, working carrier accounts/Manual Store prerequisites, and per-order warehouse/customs/shipping information. Do not put credentials or recipient information in GitHub issues.

The estimate may increase if exports reveal different joins or package layouts, account-specific Canada customs/service restrictions, provider response differences, or PDF/printer incompatibilities. No assumption of a free label-purchase sandbox is made. Account enablement, paid-label authorization and waiting for operator feedback are external elapsed-time dependencies.

## Later phases

After the local workflow is accepted: Google Cloud Run deployment, Cloud SQL migration, private Cloud Storage, Secret Manager, authenticated multiple-user access, and later differentiated permissions. Other shipping-provider adapters, richer editing, bulk PDF composition and multi-package shipments are separate follow-up work. Cloud infrastructure and associated running costs are excluded from the first-release estimate.

## GitHub issue tracking

Implementation issues are created in `hli9562/WMS2ShipStation`. The table below is populated with their links after creation. Dependencies are explicit in each issue; implementation should follow the work breakdown above.


| Issue | Work item | Hours |
| --- | --- | --- |
| [DEV-01](https://github.com/hli9562/WMS2ShipStation/issues/1) | Docker application scaffold and database migrations | 4–6 |
| [DEV-02](https://github.com/hli9562/WMS2ShipStation/issues/2) | XLSX import, preview, provenance and duplicate detection | 6–10 |
| [DEV-03](https://github.com/hli9562/WMS2ShipStation/issues/3) | Per-order configuration, shipping choices and purchase validation | 6–10 |
| [DEV-04](https://github.com/hli9562/WMS2ShipStation/issues/4) | Provider-independent purchase coordinator and recovery safeguards | 8–12 |
| [DEV-05](https://github.com/hli9562/WMS2ShipStation/issues/5) | ShipStation V1 direct-label adapter and account discovery | 6–10 |
| [DEV-06](https://github.com/hli9562/WMS2ShipStation/issues/6) | Letter PDF printing, shipment history and manual WMS tracking workflow | 4–6 |
| [DEV-07](https://github.com/hli9562/WMS2ShipStation/issues/7) | Local Docker test release, recovery checks and operator guide | 6–10 |
