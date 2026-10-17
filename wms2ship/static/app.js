const csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.querySelector('#status');
const orders = document.querySelector('#orders');
const results = document.querySelector('#import-result');

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.issues?.map(i => `${i.field}: ${i.message}`).join(' ') || 'Request failed.'));
  return data;
}

function message(parent, value, tag = 'p') {
  const element = document.createElement(tag);
  element.textContent = value;
  parent.append(element);
  return element;
}

async function loadOrders() {
  const data = await api('/api/orders');
  orders.replaceChildren();
  if (!data.length) message(orders, 'No orders imported yet.');
  for (const row of data) {
    const button = message(orders, `${row.wms_order_no} · ${row.platform_reference || 'No platform reference'}`, 'button');
    button.type = 'button';
    button.addEventListener('click', async () => {
      try {
        const order = await api(`/api/orders/${row.id}`);
        showConfiguration(order);
        document.querySelector('#preview-panel').hidden = false;
        document.querySelector('#preview-panel').scrollIntoView({ behavior: 'smooth' });
      } catch (error) { status.textContent = error.message; }
    });
  }
}

document.querySelector('#import-form').addEventListener('submit', async event => {
  event.preventDefault();
  const file = document.querySelector('#workbook').files[0];
  if (!file) return;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  status.textContent = 'Reading and validating workbook…';
  results.replaceChildren();
  try {
    const batch = await api(`/api/imports?filename=${encodeURIComponent(file.name)}`, {
      method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/octet-stream' }, body: file
    });
    status.textContent = `Import complete: ${batch.created} new, ${batch.duplicates} existing, ${batch.invalid} invalid.`;
    const detail = await api(`/api/imports/${batch.id}`);
    for (const row of detail.rows) {
      if (row.issues.length) message(results, `${row.sheet}, row ${row.row}, order ${row.source_order_no || '(missing)'}: ${row.issues.join(' ')}`);
    }
    await loadOrders();
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
loadOrders().catch(error => { status.textContent = error.message; });

let currentOrder;
let availableProviders = [{code: 'fake', mode: 'simulation', live_purchase_enabled: false}];
api('/api/providers').then(data => { availableProviders = data; }).catch(error => { status.textContent = error.message; });
function field(parent, name, label, value = '', options = null, type = 'text') {
  const wrapper = document.createElement('label');
  wrapper.textContent = label;
  const input = document.createElement(options ? 'select' : 'input');
  input.name = name;
  if (options) {
    for (const [code, title] of [['', 'Choose…'], ...options]) {
      const option = document.createElement('option');
      option.value = code;
      option.textContent = title;
      input.append(option);
    }
  } else input.type = type;
  input.value = value == null ? '' : String(value);
  wrapper.append(input);
  parent.append(wrapper);
  return input;
}
function showConfiguration(order) {
  currentOrder = order;
  document.querySelector('#order-preview').textContent = JSON.stringify(order, null, 2);
  document.querySelector('#order-summary').textContent = `${order.wms_order_no} · ${order.recipient.country} · ${order.packages[0]?.weight_g || '?'} g`;
  document.querySelector('#validation-result').replaceChildren();
  const origin = document.querySelector('#origin-fields');
  const shipping = document.querySelector('#shipping-fields');
  const customs = document.querySelector('#customs-fields');
  [origin, shipping, customs].forEach(node => node.replaceChildren());
  for (const [key, label] of Object.entries({ name: 'Contact name', company: 'Company', phone: 'Phone', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX)', postal: 'ZIP code', country: 'Country (US)' })) {
    field(origin, `origin.${key}`, label, order.origin?.[key]);
  }
  const s = order.shipping || {};
  const providerSelect = field(shipping, 'shipping.provider', 'Shipping provider', s.provider || 'fake', availableProviders.map(p => [p.code, p.mode === 'simulation' ? 'Simulation — no postage' : 'ShipStation V1 — live account']));
  const carrierSelect = field(shipping, 'shipping.carrier_code', 'Carrier', s.carrier_code, []);
  const serviceSelect = field(shipping, 'shipping.service_code', 'Service', s.service_code, []);
  const packageSelect = field(shipping, 'shipping.package_code', 'Package type', s.package_code, []);
  async function refreshCatalog(restore = false) {
    const providerCode = providerSelect.value;
    const modeInfo = availableProviders.find(p => p.code === providerCode);
    document.querySelector('#configuration-mode').textContent = providerCode === 'fake' ? 'Simulation only — not valid postage.' : `ShipStation live account. Paid purchasing is ${modeInfo?.live_purchase_enabled ? 'enabled' : 'disabled in server configuration'}.`;
    document.querySelector('#create-label').textContent = providerCode === 'fake' ? 'Create simulated label' : 'Buy shipping label';
    try {
      const catalog = await api(`/api/providers/${providerCode}/carriers`);
      if (currentOrder?.id !== order.id || providerSelect.value !== providerCode) return;
      function options(select, rows, value) {
        select.replaceChildren();
        for (const row of [{code: '', name: 'Choose…'}, ...rows]) {
          const option = document.createElement('option'); option.value = row.code; option.textContent = row.name; select.append(option);
        }
        select.value = value || '';
      }
      function updateCarrier(restoreValues = false) {
        const carrier = catalog.carriers.find(c => c.code === carrierSelect.value);
        const scope = order.recipient.country === 'CA' ? 'international' : 'domestic';
        options(serviceSelect, (carrier?.services || []).filter(s => s[scope] !== false), restoreValues ? s.service_code : '');
        options(packageSelect, carrier?.packages || [], restoreValues ? s.package_code : '');
      }
      options(carrierSelect, catalog.carriers, restore ? s.carrier_code : '');
      updateCarrier(restore);
      carrierSelect.onchange = () => updateCarrier(false);
    } catch (error) { document.querySelector('#validation-result').textContent = error.message; }
  }
  providerSelect.onchange = () => refreshCatalog(false);
  refreshCatalog(true);
  field(shipping, 'shipping.ship_date', 'Ship date', s.ship_date, null, 'date');
  field(shipping, 'shipping.timezone', 'Timezone (e.g. America/Chicago)', s.timezone);
  field(shipping, 'shipping.residential', 'Recipient address type', s.residential, [['true', 'Residential'], ['false', 'Commercial']]);
  field(shipping, 'shipping.confirmation', 'Delivery confirmation', s.confirmation, ['none', 'delivery', 'signature', 'adult_signature', 'direct_signature'].map(code => [code, code]));
  field(shipping, 'shipping.insurance', 'Insurance', s.insurance, [['none', 'None'], ['carrier', 'Carrier'], ['shipsurance', 'Shipsurance']]);
  field(shipping, 'shipping.insured_value', 'Insured value (USD, if insured)', s.insured_value);
  const canadian = order.recipient.country === 'CA';
  document.querySelector('#customs-heading').hidden = !canadian;
  customs.hidden = !canadian;
  if (canadian) {
    field(customs, 'shipping.duties_payer', 'Duties payer', s.duties_payer, [['recipient', 'Recipient']]);
    field(customs, 'customs.contents', 'Contents type', order.customs?.contents, ['merchandise', 'documents', 'gift', 'returned_goods', 'sample'].map(code => [code, code]));
    field(customs, 'customs.non_delivery', 'If undeliverable', order.customs?.non_delivery, [['return_to_sender', 'Return to sender'], ['treat_as_abandoned', 'Treat as abandoned']]);
    order.items.forEach((item, index) => {
      const declaration = order.customs?.items?.find(d => d.item_id === item.id) || {};
      message(customs, `${item.sku} · quantity ${item.quantity}`, 'h4');
      for (const [key, label] of Object.entries({ description: 'Customs description', unit_value: 'Declared unit value', currency: 'Currency (USD)', country_of_origin: 'Origin country (2 letters)', hs_code: 'HS code (6–10 digits)' })) {
        field(customs, `customs.${index}.${key}`, label, declaration[key]);
      }
    });
  }
}
function formValue(name) {
  return document.querySelector('#configuration-form').elements.namedItem(name)?.value || '';
}
async function saveConfiguration() {
  if (!currentOrder) return;
  const origin = {};
  for (const input of document.querySelectorAll('#origin-fields input')) origin[input.name.split('.')[1]] = input.value;
  const shipping = {};
  for (const input of document.querySelectorAll('#shipping-fields input, #shipping-fields select')) shipping[input.name.split('.')[1]] = input.value;
  shipping.ship_date = shipping.ship_date || null;
  shipping.residential = shipping.residential === '' ? null : shipping.residential === 'true';
  shipping.duties_payer = formValue('shipping.duties_payer');
  let customs = null;
  if (currentOrder.recipient.country === 'CA') {
    customs = { contents: formValue('customs.contents'), non_delivery: formValue('customs.non_delivery'), items: currentOrder.items.map((item, index) => ({
      item_id: item.id, quantity: item.quantity,
      ...Object.fromEntries(['description', 'unit_value', 'currency', 'country_of_origin', 'hs_code'].map(key => [key, formValue(`customs.${index}.${key}`)]))
    })) };
  }
  const order = await api(`/api/orders/${currentOrder.id}`, { method: 'PATCH', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify({ version: currentOrder.version, origin, shipping, customs }) });
  showConfiguration(order);
  return order;
}
document.querySelector('#configuration-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await saveConfiguration(); document.querySelector('#validation-result').textContent = 'Configuration saved. Check readiness before purchase.'; }
  catch (error) { document.querySelector('#validation-result').textContent = error.message; }
});
document.querySelector('#validate-order').addEventListener('click', async () => {
  const target = document.querySelector('#validation-result');
  try {
    const order = await saveConfiguration();
    const result = await api(`/api/orders/${order.id}/validate`, { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
    target.replaceChildren();
    if (result.valid) message(target, result.mode === 'simulation' ? 'Ready for a simulated purchase — not usable postage.' : 'Required fields are complete. Review the shipment before buying postage.');
    for (const issue of result.issues) message(target, `${issue.field}: ${issue.message}`);
  } catch (error) { target.textContent = error.message; }
});

// Keep the request token until success/failure is known; an uncertain request must not be repurchased.
const purchaseTokens = new Map();
document.querySelector('#create-label').addEventListener('click', async event => {
  if (!currentOrder) return;
  const button = event.currentTarget;
  button.disabled = true;
  const target = document.querySelector('#purchase-result');
  try {
    const selected = formValue('shipping.provider');
    if (selected === 'shipstation' && !window.confirm('Buy a real shipping label for this order? This charges your connected carrier account.')) return;
    const order = await saveConfiguration();
    const key = `${order.id}:${order.version}`;
    if (!purchaseTokens.has(key)) purchaseTokens.set(key, crypto.randomUUID());
    const attempt = await api(`/api/orders/${order.id}/label-attempts`, {
      method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: order.version, package_id: order.packages[0].id, request_token: purchaseTokens.get(key), confirm_purchase: true })
    });
    await loadHistory(true);
    target.textContent = ` ${attempt.mode === 'simulation' ? 'SIMULATION — NOT VALID POSTAGE.' : 'ShipStation purchase.'} Attempt ${attempt.id}: ${attempt.state}. ${attempt.labels.map(l => l.tracking_number).join(', ')}`;
  } catch (error) { target.textContent = error.message; }
  finally { button.disabled = false; }
});

let historyOffset = 0;
async function loadHistory(reset = false) {
  const target = document.querySelector('#history');
  if (reset) { historyOffset = 0; target.replaceChildren(); }
  const rows = await api(`/api/history?offset=${historyOffset}`);
  if (!rows.length && historyOffset === 0) message(target, 'No label attempts yet.');
  for (const row of rows) {
    const card = document.createElement('article');
    message(card, `${row.wms_order_no} · ${row.mode.toUpperCase()} · ${row.state}`, 'h3');
    message(card, `Tracking: ${row.tracking_number || 'Not available'} · ${row.created_at}`);
    message(card, `Attempt: ${row.attempt_id}`);
    if (row.error_code) message(card, `Action required: ${row.error_code}`);
    if (row.label_id) {
      for (const kind of ['letter', 'original']) {
        const link = message(card, kind === 'letter' ? 'Open Letter PDF / print' : 'Open original PDF', 'a');
        link.href = `/api/labels/${row.label_id}/pdf?kind=${kind}`; link.target = '_blank'; link.rel = 'noopener';
      }
    }
    target.append(card);
  }
  historyOffset += rows.length;
  document.querySelector('#more-history').hidden = rows.length < 50;
}
document.querySelector('#refresh-history').addEventListener('click', () => loadHistory(true).catch(error => { status.textContent = error.message; }));
document.querySelector('#more-history').addEventListener('click', () => loadHistory(false).catch(error => { status.textContent = error.message; }));
loadHistory(true).catch(error => { status.textContent = error.message; });
