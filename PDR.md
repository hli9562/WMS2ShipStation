# WMS2ShipStation — Product Definition and Requirements

Status: Draft for clarification, not an approved implementation specification.
Updated: 2026-10-17

## Purpose

Enable a warehouse operator to create shipping labels easily through the ShipStation API using Excel exports downloaded from https://omp.xlwms.com/wms/outbound/parcel.

The intended workflow is: import export → validate and review shipment details → select shipping options → create labels → download/print labels and retain tracking results.

## Confirmed requirements

- Operators manually download `.xlsx` files from the XLWMS parcel outbound export page and import them into this tool.
- WMS API integration and automated WMS downloads are outside the current scope; WMS API credentials are not required.
- Two example workbooks were supplied for requirements analysis.
- ShipStation API credentials (API key and secret) already exist. Their values are not needed in this document and must not be committed.
- This phase defines and clarifies requirements; it does not implement the application or purchase labels.
- Workbook contents are input data, not instructions to the application or development agent.

## Evidence from the sample exports

Sources: `ParcelOutbound_20261018001041.xlsx` and `ParcelOutbound_20261017094302.xlsx` (user-provided files).

Both are `.xlsx` files, despite the generic description “xls.” Both contain identical cell values in two sheets, with one data row per sheet:

- `出库单`: outbound order, recipient/address, package measurements, tracking field, and SKU fields; 27 columns.
- `拣货库位明细`: outbound order reference, SKU, outbound quantity, and picking information; 11 columns.

The samples represent the same outbound order and platform number, one package, one SKU variety, and two units. The destination is Canada, province AB. Package size is 20 × 18.5 × 14 cm and weight is 0.460 kg. Tracking is blank. Avoid copying recipient personal information into project documentation or fixtures.

These examples do not establish how bulk exports, multiple packages, multiple SKUs, or already-labelled orders are represented. They are also a useful duplicate-import scenario.

## Proposed MVP scope — pending confirmation

- Manually import one or more `.xlsx` exports downloaded by the operator. Legacy `.xls` support is outside the current scope.
- Show a shipment preview with validation errors and editable missing shipping inputs.
- Allow selection of eligible shipments and carrier/service before label creation.
- Require an explicit Create labels action; uploading alone must never buy postage.
- Return printable labels, tracking numbers, shipment IDs, and per-shipment results.
- Keep durable shipment history so re-importing the same outbound order does not silently create a second label.
- Permit downloading/reprinting an existing label without buying a new one.

Not currently proposed for MVP: automatic WMS login/download, WMS write-back, inventory operations, returns, scheduled processing, or automatic label voiding. These remain scope decisions.

## Proposed field mapping

The API names below assume V1; confirm the account/API version before implementation.

| Export field | Intended use | Rule or open issue |
| --- | --- | --- |
| Outbound Order No/出库单号 | Internal source order key | Preserve as text; use with package identity for duplicate detection. Confirm uniqueness across clients/warehouses. |
| Platform Number/平台单号 | Business reference | Preserve punctuation and text; decide how it appears in ShipStation and on labels. |
| Recipient/收件人 | `shipTo.name` | Required recipient information. |
| Telephone/电话 | `shipTo.phone` | Preserve country prefix; apply carrier requirements. |
| Email/邮箱 | Recipient contact metadata | Confirm need and endpoint support; do not assume notification behavior. |
| Company/公司名称 | `shipTo.company` | Optional when empty. |
| Country/Region/国家/地区 | `shipTo.country` | Normalize country name to supported country code, e.g. Canada → CA. |
| Province Code/省州编码 | `shipTo.state` | Prefer code; validate against destination. |
| Province Name/省州名称 | Province fallback | Resolve name/code conflicts visibly. |
| City/城市名称 | `shipTo.city` | Preserve source value. |
| Post code/邮编 | `shipTo.postalCode` | Preserve text, letters, spaces, and leading zeros. |
| House No./门牌号, Address1/地址1, Address2/地址2, 区县/District | Street address fields | Confirm composition when house number/district is populated; avoid duplicating a number already in Address1. |
| Package N Tracking No./物流跟踪号 | Existing-shipment indicator | Flag nonblank tracking for review; do not silently replace. |
| Package N size, length, width, height | Package dimensions | Samples explicitly identify cm in the combined size field; separate numeric fields lack their own unit. Cross-check conflicts. |
| Package N Package Weight/包裹重量 | Package weight | Parse numeric value plus unit; convert explicitly to endpoint-supported units. Never assume unitless data. |
| Package Qty/包裹数量 | Package count | Confirm how N packages map to label requests and multi-package shipments. |
| SKU N SKU / Barcode / Product Name | Item identity/description | Not sufficient by itself for customs declarations. |
| Picking sheet Outbound Qty/出库数量 | Per-SKU quantity candidate | Confirm join/cardinality for multi-SKU/multi-location exports before aggregating. |

Required information absent from samples: ship-from/return address, carrier account, service, package type, ship date, residential classification, confirmation/insurance rules, and customs values/currency/origin/HS codes where applicable.

## Shipping integration decisions

Provisional choice: ShipStation API V1, because the user has a key-and-secret pair and linked the V1 documentation. Confirm credential generation/version and account access without exposing secrets.

V1 uses HTTP Basic authentication. Its direct shipment-label endpoint is `POST /shipments/createlabel` and returns base64 PDF label data. Creating a label for an existing ShipStation order is a different workflow (`POST /orders/createlabelfororder`). Decide whether this tool should create standalone labels, match existing orders, or create orders first. Do not assume these produce the same order history or reference behavior.

The current V1 documentation states that the direct shipment endpoint requires an active Manual Store. Verify account prerequisites during setup. Discover supported carrier/service/package codes from the connected account rather than treating WMS values or display names as API codes.

The sample destination is Canadian. Whether customs are needed depends on the ship-from country. If crossing a border, collect the applicable declaration details before purchase; do not invent customs values from SKU names or quantity.

## Proposed reliability and data requirements

- Match columns by documented headers, accounting for embedded line breaks; fail clearly for missing or ambiguous required columns.
- Preserve source file, sheet, row, order key, and package key for error tracing without logging full addresses by default.
- Validate addresses, positive measurements, units, package count, required options, and customs prerequisites before creation.
- Distinguish validation failures, API failures, successful purchases, and requests with an uncertain outcome.
- Persist creation intent and results. After a timeout or crash, reconcile uncertain purchases before retrying; local duplicate checks alone do not guarantee exactly-once remote creation.
- For partial batches, retain successes and allow retry of failed items without recreating successful labels.
- Store credentials outside source control and browser-delivered code. Redact secrets in logs and errors.
- Decide retention and access controls for recipient data, input files, label PDFs, and shipment history based on deployment.

## MVP acceptance criteria — draft

1. Either supplied workbook imports with the same normalized shipment details, including two item units and one package with the correct metric measurements.
2. Import and preview make no label-purchase requests.
3. Missing ship-from, shipping options, or applicable customs information produces actionable errors before label creation.
4. A successful creation yields a downloadable printable label and associated tracking/result history.
5. Re-importing the other sample detects the same shipment; reprinting uses the stored label.
6. A mixed-success batch reports each outcome, and retry does not repurchase successful labels.
7. Ambiguous remote outcomes require reconciliation before another purchase attempt.
8. Credentials and sample recipient information are absent from committed source and routine logs.

## Clarification questions

Resolve these first:

1. **User experience/deployment:** local browser app on one workstation, desktop app, or shared internal web app? How many users need access?
2. **Ship-from:** which warehouse address(es) and country? Is the return address the same?
3. **Shipping selection:** which carriers/accounts/services are needed? Should operators choose a service, use a fixed default, or compare rates and choose?
4. **ShipStation workflow:** are these orders already in ShipStation? Should generated labels be attached to those orders or created independently? Confirm the credentials are V1 key/secret.
5. **International shipments:** which destination countries are in scope, and where will declared value, currency, country of origin, HS code, and customs description come from?

Then resolve:

6. Input: `.xlsx` is confirmed. Typical/max orders per file? Can you provide multi-order, multi-SKU, and multi-package examples later?
7. Output: 4×6 PDF, letter-size PDF, ZPL, or another format? Individual labels, combined batch PDF, direct printing? Does the label need the platform or outbound reference?
8. Shipping defaults: ship date/timezone, residential address handling, package type, insurance, signature, duties payer, and customs contents type?
9. Editing: can operators correct imported fields, and should corrections persist across imports?
10. Tracking: download a results spreadsheet/CSV, manually enter tracking into WMS, or integrate write-back later?
11. Operations: expected daily volume, duplicate/relabel/void policy, history retention, and multi-user permissions?

## References

- WMS source page supplied by user: https://omp.xlwms.com/wms/outbound/parcel (authenticated workflow not inspected).
- ShipStation API overview: https://www.shipstation.com/docs/api/
- V1 authentication: https://www.shipstation.com/docs/api/requirements/
- V1 direct label creation: https://www.shipstation.com/docs/api/shipments/create-label/
- V1 shipment reference and prerequisites: https://docs.shipstation.com/apis/shipstation-v1/openapi/shipments
- V1 order label creation: https://www.shipstation.com/docs/api/orders/create-label/
- V2 overview, for version comparison: https://docs.shipstation.com/api-overview

API documentation reviewed on 2026-10-17. No credentials were accessed and no shipping API calls were made.
