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

## Confirmed operating decisions

- Start with a local web app; plan for later deployment to Google Cloud and access by multiple users.
- Use one warehouse in Katy, Texas, USA. The return address is the same as the ship-from address. The operator configures the complete warehouse address and contact details per order before purchasing its label; use that same address for returns.
- Operators choose the carrier. Available accounts and service selection details remain to be confirmed.
- Orders are not in ShipStation. Create shipment labels directly without first creating ShipStation orders. The existing credentials are confirmed as V1 API key/secret.
- ShipStation is the initial shipping integration. Keep import, validation, duplicate detection, and shipment history independent of provider-specific API fields so other shipping providers can be added later. Additional providers are outside the MVP scope.
- Destinations are limited to the United States and Canada. Canadian shipments originate in the US and require applicable customs information.
- Initial volume is fewer than 10 orders per day; the planning envelope is fewer than 100 orders per day. This does not establish a maximum file size.
- Output is Letter-size PDF, printable on a printer available at the user's computer. Printing should be available through the local browser/PDF viewer; silent direct printing is not yet required.
- Editing imported information is a desired enhancement to correct errors or incompatible formats; whether full editing is required for MVP remains to be decided.
- Operators manually enter tracking results into WMS for now.
- WMS order numbers are unique within the current operation. Preserve them as text and use them with package identity for duplicate detection.
- Label generation follows the applicable ShipStation V1 documentation. Retry, reprint, replacement, and void behavior must preserve purchase history and avoid unintended duplicate purchases.
- Retain all shipment history for now, with no automatic history deletion. Current users have full application access; differentiated permissions are a future requirement. Retention of raw input files and recipient data outside shipment history remains to be defined.
- The operator configures shipping options per order, including applicable ship date/timezone, residential handling, package type, insurance, signature, duties payer, and customs contents type. No universal shipping defaults are assumed.
- For each Canadian shipment, the operator supplies the applicable customs data per order, including declared value, currency, country of origin, HS code, and customs description. Required data must pass validation before label purchase.

## Evidence from the sample exports

Sources: `ParcelOutbound_20261018001041.xlsx` and `ParcelOutbound_20261017094302.xlsx` (user-provided files).

Both are `.xlsx` files, despite the generic description “xls.” Both contain identical cell values in two sheets, with one data row per sheet:

- `出库单`: outbound order, recipient/address, package measurements, tracking field, and SKU fields; 27 columns.
- `拣货库位明细`: outbound order reference, SKU, outbound quantity, and picking information; 11 columns.

The samples represent the same outbound order and platform number, one package, one SKU variety, and two units. The destination is Canada, province AB. Package size is 20 × 18.5 × 14 cm and weight is 0.460 kg. Tracking is blank. Avoid copying recipient personal information into project documentation or fixtures.

These examples do not establish how bulk exports, multiple packages, multiple SKUs, or already-labelled orders are represented. They are also a useful duplicate-import scenario.

## MVP scope — confirmed input and proposed application behavior

- Manually import one or more `.xlsx` exports downloaded by the operator. Legacy `.xls` support is outside the current scope.
- Show a shipment preview with validation errors and per-order forms for warehouse address/contact details, applicable customs data, and shipping options. These forms are required MVP behavior; broader editing of imported fields remains a desired enhancement.
- Allow selection of eligible shipments and carrier/service before label creation.
- Require an explicit Create labels action; uploading alone must never buy postage.
- Return printable labels, tracking numbers, shipment IDs, and per-shipment results.
- Keep durable shipment history so re-importing the same outbound order does not silently create a second label.
- Permit downloading/reprinting an existing label without buying a new one.

Not currently proposed for MVP: automatic WMS login/download, WMS write-back, inventory operations, returns, scheduled processing, or automatic label voiding. These remain scope decisions.

## Proposed field mapping

The API names below target the confirmed ShipStation V1 API.

| Export field | Intended use | Rule or open issue |
| --- | --- | --- |
| Outbound Order No/出库单号 | Internal source order key | Preserve as text; use with package identity for duplicate detection. Uniqueness is confirmed for the current operation; revisit namespace rules when adding clients/warehouses. |
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

Confirmed choice: ShipStation API V1 with the existing API key/secret. Verify account access during setup without exposing secrets.

Use the V1 direct shipment-label workflow: `POST /shipments/createlabel`, with HTTP Basic authentication and base64 PDF label data in the response. Do not create ShipStation orders first. Keep source-order, package, label, tracking, and purchase history in this application.

Keep shipping-provider integration behind a separate boundary. Record the provider and its shipment/label identifiers with each result; retain the original provider association when reprinting or reconciling a purchase. Adding another provider later must not bypass duplicate-purchase checks for the same source order/package.

The current V1 documentation states that the direct shipment endpoint requires an active Manual Store. Verify account prerequisites during setup. Discover supported carrier/service/package codes from the connected account rather than treating WMS values or display names as API codes.

Shipments originate in Katy, Texas, and go to the US or Canada. For Canadian shipments, collect the applicable customs declaration details before purchase; do not invent customs values from SKU names or quantity.

## Proposed reliability and data requirements

- Match columns by documented headers, accounting for embedded line breaks; fail clearly for missing or ambiguous required columns.
- Preserve source file, sheet, row, order key, and package key for error tracing without logging full addresses by default.
- Validate addresses, positive measurements, units, package count, required options, and customs prerequisites before creation.
- Distinguish validation failures, API failures, successful purchases, and requests with an uncertain outcome.
- Persist creation intent and results. After a timeout or crash, reconcile uncertain purchases before retrying; local duplicate checks alone do not guarantee exactly-once remote creation.
- For partial batches, retain successes and allow retry of failed items without recreating successful labels.
- Store credentials outside source control and browser-delivered code. Redact secrets in logs and errors.
- Retain all shipment history for now and give current users full application access. Define raw-file and recipient-data retention, cloud authentication, and differentiated permissions before the corresponding deployment changes.

## MVP acceptance criteria — draft

1. Either supplied workbook imports with the same normalized shipment details, including two item units and one package with the correct metric measurements.
2. Import and preview make no label-purchase requests.
3. Missing ship-from, shipping options, or applicable customs information produces actionable errors before label creation.
4. A successful creation yields a downloadable printable label and associated tracking/result history.
5. Re-importing the other sample detects the same shipment; reprinting uses the stored label.
6. A mixed-success batch reports each outcome, and retry does not repurchase successful labels.
7. Ambiguous remote outcomes require reconciliation before another purchase attempt.
8. Credentials and sample recipient information are absent from committed source and routine logs.
9. For each order, the operator can configure the Katy warehouse address/contact details, applicable customs data, and shipping options before purchase. The same warehouse address is used for ship-from and return. Missing or invalid required values block purchase. The app supports only US/Canada destinations and lets the operator choose the carrier.
10. Labels can be downloaded as Letter-size PDFs and printed using the user's local printer; tracking results are available for manual entry into WMS.
11. Shipment history survives application restarts and has no automatic deletion. Verify processing at the planned volume of fewer than 100 orders per day.

## Remaining clarification questions

Warehouse address/contact details, Canadian customs data, and shipping options are confirmed as per-order user configuration, not unresolved product decisions.

1. **Carrier and service selection:** which carrier accounts/services are available, how the service is selected, and whether rate comparison is needed.
2. **Direct-label setup:** confirm account prerequisites and how WMS/platform references appear in ShipStation and on labels. The direct shipment-label workflow is confirmed.
3. **Input edge cases:** maximum orders per file and multi-order, multi-SKU, multi-location, and multi-package examples; address composition and quantity aggregation rules.
4. **PDF and printing:** individual PDFs or a combined batch PDF, and label placement/scaling on Letter paper. Confirm that barcodes remain readable when printed.
5. **Editing enhancement:** MVP priority, editable fields, and whether corrections persist across imports.
6. **Label lifecycle:** explicit replacement/void policy consistent with ShipStation documentation; handling of existing WMS tracking numbers.
7. **Future deployment:** cloud hosting, authentication, multiple-user access, differentiated permissions, and retention of raw files and recipient data outside shipment history.

## References

- WMS source page supplied by user: https://omp.xlwms.com/wms/outbound/parcel (authenticated workflow not inspected).
- ShipStation API overview: https://www.shipstation.com/docs/api/
- V1 authentication: https://www.shipstation.com/docs/api/requirements/
- V1 direct label creation: https://www.shipstation.com/docs/api/shipments/create-label/
- V1 shipment reference and prerequisites: https://docs.shipstation.com/apis/shipstation-v1/openapi/shipments
- V1 order label creation: https://www.shipstation.com/docs/api/orders/create-label/
- V2 overview, for version comparison: https://docs.shipstation.com/api-overview

API documentation reviewed on 2026-10-17. No credentials were accessed and no shipping API calls were made.
