# ShipStation V1 shipping options

Reviewed against official V1 documentation on October 17, 2026. This app uses
`POST /shipments/createlabel` with V1 key/secret authentication. V2-only fields
are not interchangeable with this integration.

## Available in the order editor

| Choice | V1 source or field | Behavior |
| --- | --- | --- |
| Carrier | `/carriers` | Connected primary carrier account; no hardcoded carrier list. |
| Service | `/carriers/listservices` | Radio choices filtered by domestic/international destination. |
| Package type | `/carriers/listpackages` | Radio choices filtered by destination flags when returned. |
| Delivery confirmation | `confirmation` | None, delivery, signature, adult signature; direct signature for FedEx only. |
| Insurance | `insuranceOptions` | None, carrier, Shipsurance, XCover, ParcelGuard, or other insurance (`provider`); insured value required when selected. |
| Saturday delivery | `advancedOptions.saturdayDelivery` | Optional Yes/No; defaults to No for old orders. |
| Non-machinable handling | `advancedOptions.nonMachinable` | Optional Yes/No; defaults to No. |
| Alcohol contents | `advancedOptions.containsAlcohol` | Optional Yes/No; defaults to No. |
| Ship date / recipient type | `shipDate` / `shipTo.residential` | Configured per order. |
| Canada declarations | `internationalOptions` | Contents, customs items, and non-delivery instructions. |

Optional services and insurance remain subject to carrier/service/account
availability and may change the final cost. Other insurance (`provider`) is
arranged and billed outside ShipStation. The carrier list does not supply a
complete compatibility matrix for every insurance or advanced option.
Historical attempts preserve all selections in the request snapshot.

## API features outside this update

- `/shipments/getrates` supports rate lookup; the current app does not display
  quotes. Do not interpret selecting a service as obtaining a price quote.
- The separate USPS test-label provider sends `testLabel: true` for dedicated
  US synthetic orders using Stamps.com, with no insurance/add-ons. Paid label
  creation remains gated separately. Offline Simulation is still available.
  History and reports identify USPS test activity as `test`, distinct from live.
- Billing to another account/recipient/third party and order custom fields are
  documented for the order workflow. They are not exposed for standalone labels.
- Manual-store/account configuration and the primary-account limitation remain.
  This change does not enable purchases or create ShipStation orders.

## Official references

- [Create shipment label](https://www.shipstation.com/docs/api/shipments/create-label/)
- [List carriers](https://www.shipstation.com/docs/api/carriers/list/)
- [List services](https://www.shipstation.com/docs/api/carriers/list-services/)
- [List packages](https://www.shipstation.com/docs/api/carriers/list-packages/)
- [Insurance options](https://www.shipstation.com/docs/api/models/insurance-options/)
- [Advanced options](https://www.shipstation.com/docs/api/models/advanced-options/)
- [International options](https://www.shipstation.com/docs/api/models/international-options/)
- [Get rates](https://www.shipstation.com/docs/api/shipments/get-rates/)
