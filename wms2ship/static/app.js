const csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.querySelector('#status');
const orders = document.querySelector('#orders');
const results = document.querySelector('#import-result');

const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(name) {
  const selected = tabs.find(tab => tab.id === `tab-${name}`) || tabs[0];
  for (const tab of tabs) {
    const active = tab === selected;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !active;
  }
}
function openTab(name) {
  selectTab(name);
  if (location.hash !== `#${name}`) location.hash = name;
}
for (const [index, tab] of tabs.entries()) {
  tab.addEventListener('click', () => openTab(tab.id.slice(4)));
  tab.addEventListener('keydown', event => {
    const positions = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 };
    if (!(event.key in positions)) return;
    event.preventDefault();
    const next = tabs[positions[event.key]];
    openTab(next.id.slice(4));
    next.focus();
  });
}
document.querySelectorAll('[data-open-tab]').forEach(button => {
  button.addEventListener('click', () => {
    openTab(button.dataset.openTab);
    document.getElementById(`tab-${button.dataset.openTab}`).focus();
  });
});
window.addEventListener('hashchange', () => selectTab(location.hash.slice(1)));
selectTab(location.hash.slice(1));

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const issues = Array.isArray(detail)
      ? detail.map(issue => `${(issue.loc || []).filter(part => part !== 'body').join('.')}: ${issue.msg}`)
      : detail?.issues?.map(issue => `${issue.field}: ${issue.message}`);
    throw new Error(typeof detail === 'string' ? detail : (issues?.join(' ') || `Request failed (${response.status}).`));
  }
  return data;
}

function message(parent, value, tag = 'p') {
  const element = document.createElement(tag);
  element.textContent = value;
  parent.append(element);
  return element;
}

let importedOrders = [];
let orderOffset = 0;
let orderRevision = 0;
let orderSearchTimer;
const selectedLabels = new Set();
function updateBatchButton() {
  const button = document.querySelector('#batch-print');
  button.disabled = !selectedLabels.size;
  button.textContent = `Open selected labels (${selectedLabels.size})`;
}
function renderOrders() {
  orders.replaceChildren();
  document.querySelector('#order-list-status').textContent = importedOrders.length
    ? `Orders ${orderOffset + 1}–${orderOffset + importedOrders.length} · newest imported first`
    : 'No matching orders.';
  if (!importedOrders.length) message(message(orders, '', 'tr'), 'No matching orders.', 'td').colSpan = 7;
  for (const row of importedOrders) {
    const tr = message(orders, '', 'tr');
    if (!row.label_status) tr.className = 'new-order';
    const selectCell = message(tr, '', 'td');
    if (row.label_id) {
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.setAttribute('aria-label', `Print ${row.wms_order_no}`);
      checkbox.checked = selectedLabels.has(row.label_id);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked && selectedLabels.size >= 100) {
          checkbox.checked = false;
          document.querySelector('#batch-print-status').textContent = 'Select up to 100 labels per PDF.';
          return;
        }
        if (checkbox.checked) selectedLabels.add(row.label_id); else selectedLabels.delete(row.label_id);
        updateBatchButton();
      });
      selectCell.append(checkbox);
    } else selectCell.textContent = '—';
    const link = message(message(tr, '', 'td'), row.wms_order_no, 'a');
    link.href = '#orders';
    message(tr, row.platform_reference || '—', 'td');
    message(tr, row.recipient_name || '—', 'td');
    message(tr, row.tracking_number || '—', 'td');
    const date = message(tr, new Date(row.created_at).toLocaleString(), 'td');
    date.title = row.created_at;
    const mode = row.provider_code === 'fake' ? ' · SIMULATION' : row.provider_code === 'shipstation_test' ? ' · TEST' : '';
    message(tr, row.label_status ? row.label_status.replaceAll('_', ' ') + mode : 'New · no label attempts', 'td');
    link.addEventListener('click', async event => {
      event.preventDefault();
      try {
        const order = await api(`/api/orders/${row.id}`);
        await showConfiguration(order);
        document.querySelector('#no-order-selected').hidden = true;
        document.querySelector('#preview-panel').hidden = false;
        openTab('orders');
        document.querySelector('#preview-panel').scrollIntoView({ behavior: 'smooth' });
      } catch (error) { status.textContent = error.message; }
    });
  }
}
async function loadOrders(reset = true) {
  const revision = ++orderRevision;
  if (reset) orderOffset = 0;
  selectedLabels.clear();
  updateBatchButton();
  importedOrders = [];
  orders.replaceChildren();
  document.querySelector('#order-list-status').textContent = 'Loading orders…';
  document.querySelector('#orders-previous').disabled = true;
  document.querySelector('#orders-next').disabled = true;
  const params = new URLSearchParams({search: document.querySelector('#order-search').value,
    status: document.querySelector('#order-status').value, offset: orderOffset, limit: 101});
  const rows = await api(`/api/orders?${params}`);
  if (revision !== orderRevision) return;
  importedOrders = rows.slice(0, 100);
  document.querySelector('#orders-previous').disabled = orderOffset === 0;
  document.querySelector('#orders-next').disabled = rows.length <= 100;
  renderOrders();
}
function reloadOrders() { loadOrders().catch(error => { status.textContent = error.message; }); }
document.querySelector('#order-search').addEventListener('input', () => {
  clearTimeout(orderSearchTimer);
  ++orderRevision;
  clearPrintSelection();
  orderSearchTimer = setTimeout(reloadOrders, 250);
});
document.querySelector('#order-status').addEventListener('change', reloadOrders);
document.querySelector('#tab-import').addEventListener('click', reloadOrders);
for (const [id, delta] of [['orders-previous', -100], ['orders-next', 100]]) {
  document.getElementById(id).addEventListener('click', () => {
    orderOffset = Math.max(0, orderOffset + delta);
    loadOrders(false).catch(error => { status.textContent = error.message; });
  });
}
function clearPrintSelection() { selectedLabels.clear(); renderOrders(); updateBatchButton(); }
document.querySelector('#clear-printable').addEventListener('click', clearPrintSelection);
document.querySelector('#select-printable').addEventListener('click', () => {
  importedOrders.filter(row => row.label_id).forEach(row => selectedLabels.add(row.label_id));
  renderOrders(); updateBatchButton();
});
let batchPdfUrl;
document.querySelector('#batch-print').addEventListener('click', async event => {
  const button = event.currentTarget;
  const output = document.querySelector('#batch-print-status');
  button.disabled = true;
  output.textContent = 'Preparing labels…';
  try {
    const response = await fetch('/api/labels/batch-print', {method: 'POST',
      headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'},
      body: JSON.stringify({label_ids: [...selectedLabels]})});
    if (!response.ok) { const error = await response.json(); throw new Error(typeof error.detail === 'string' ? error.detail : 'Unable to prepare labels.'); }
    if (batchPdfUrl) URL.revokeObjectURL(batchPdfUrl);
    batchPdfUrl = URL.createObjectURL(await response.blob());
    output.replaceChildren();
    const link = message(output, 'Open combined 4 × 6 PDF to print', 'a');
    link.href = batchPdfUrl; link.target = '_blank'; link.rel = 'noopener';
    message(output, 'Select Actual size / 100% in the print dialog.');
  } catch (error) { output.textContent = error.message; }
  finally { updateBatchButton(); }
});

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
    document.dispatchEvent(new Event('wms-import-complete'));
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
loadOrders().catch(error => { status.textContent = error.message; });

let currentOrder;
let labelRequestInFlight = false;
let readinessRevision = 0;
let readinessTimer;
let shipmentReady = false;
let catalogLoaded = false;
const packageUnits = [
  ['weight_g', 'Weight (oz)', 28.349523125],
  ['length_mm', 'Length (in)', 25.4],
  ['width_mm', 'Width (in)', 25.4],
  ['height_mm', 'Height (in)', 25.4]
];
function updateCreateLabel() {
  document.querySelector('#create-label').disabled = !shipmentReady || labelRequestInFlight || !ratePurchaseAllowed();
  updateRatePurchaseText();
  renderShipmentReview();
}
function scheduleReadiness() {
  checkRateChanges();
  const revision = ++readinessRevision;
  clearTimeout(readinessTimer);
  shipmentReady = false;
  updateCreateLabel();
  if (!currentOrder || !catalogLoaded) return;
  document.querySelector('#validation-result').textContent = 'Checking shipping details…';
  readinessTimer = setTimeout(async () => {
    const target = document.querySelector('#validation-result');
    try {
      const result = await api(`/api/orders/${currentOrder.id}/readiness`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
        body: JSON.stringify(configurationPayload())
      });
      if (revision !== readinessRevision) return;
      target.replaceChildren();
      shipmentReady = result.valid;
      if (result.valid) message(target, result.mode === 'live' ? (ratePurchaseAllowed() ? 'Ready to buy a shipping label. Your carrier account will be charged.' : 'Shipping details complete. Compare rates and select a service before buying.') : result.mode === 'test' ? (ratePurchaseAllowed() ? 'Ready to create a test label.' : 'Get quotes and select a service in step 2.') : 'Ready to create a simulated label.');
      for (const issue of result.issues) message(target, `${issue.field}: ${issue.message}`);
    } catch (error) {
      if (revision !== readinessRevision) return;
      target.textContent = error.message;
    }
    if (revision === readinessRevision) updateCreateLabel();
  }, 350);
}
let availableProviders = [{code: 'fake', mode: 'simulation', live_purchase_enabled: false}];
const providersReady = api('/api/providers').then(data => {
  availableProviders = data;
  status.textContent = data.some(p => p.mode === 'live') ? 'Workspace ready. ShipStation credentials configured; verify account access in the order form.' : 'Workspace ready. Simulation provider available.';
}).catch(error => { status.textContent = error.message; });
function field(parent, name, label, value = '', options = null, type = 'text') {
  if (options) {
    const group = document.createElement('fieldset');
    group.className = 'radio-field';
    group.dataset.field = name;
    message(group, label, 'legend');
    const choices = document.createElement('div');
    choices.className = 'radio-options';
    group.append(choices);
    parent.append(group);
    const control = {
      get value() { return choices.querySelector('input:checked')?.value || ''; },
      onchange: null,
      setOptions(rows, selected = '') {
        choices.replaceChildren();
        if (!rows.length) message(choices, 'Choose the option above to see available choices.', 'span');
        for (const [code, title] of rows) {
          const wrapper = document.createElement('label');
          const input = document.createElement('input');
          input.type = 'radio';
          input.name = name;
          input.value = code;
          input.checked = code === String(selected ?? '');
          wrapper.append(input, document.createTextNode(title));
          choices.append(wrapper);
        }
      }
    };
    choices.addEventListener('change', () => control.onchange?.());
    control.setOptions(options, value);
    return control;
  }
  const wrapper = document.createElement('label');
  wrapper.dataset.field = name;
  wrapper.textContent = label;
  const input = document.createElement('input');
  input.name = name;
  input.type = type;
  input.value = value == null ? '' : String(value);
  if (name === 'country' || name.endsWith('.country') || name.endsWith('.country_of_origin')) {
    input.maxLength = 2;
    input.placeholder = 'US / CA';
    input.pattern = '[A-Za-z]{2}';
    input.value = input.value.toUpperCase();
    input.addEventListener('input', () => { input.value = input.value.toUpperCase(); });
  }
  wrapper.append(input);
  parent.append(wrapper);
  return input;
}
async function showConfiguration(order) {
  await providersReady;
  await contactsReady;
  await workspaceSettingsReady;
  currentOrder = order;
  document.querySelector('#basic-step').open = true;
  resetRateComparison();
  catalogLoaded = false;
  scheduleReadiness();
  const preview = { ...order, packages: order.packages.map(packageData => {
    const converted = { ...packageData };
    for (const [metric, , factor] of packageUnits) {
      const us = metric === 'weight_g' ? 'weight_oz' : metric.replace('_mm', '_in');
      const raw = packageData[us] ?? (packageData[metric] == null ? null : packageData[metric] / factor);
      converted[us] = raw == null ? null : Math.ceil(raw);
      delete converted[metric];
    }
    return converted;
  }) };
  document.querySelector('#order-preview').textContent = JSON.stringify(preview, null, 2);
  const weightOz = order.packages[0]?.weight_oz ?? order.packages[0]?.weight_g / 28.349523125;
  document.querySelector('#order-summary').textContent = `${order.wms_order_no} · ${order.recipient.country} · ${weightOz ? Math.ceil(weightOz) : '?'} oz`;
  document.querySelector('#validation-result').replaceChildren();
  const origin = document.querySelector('#origin-fields');
  const shipping = document.querySelector('#shipping-fields');
  const customs = document.querySelector('#customs-fields');
  const packageFields = document.querySelector('#package-fields');
  [origin, shipping, customs, packageFields, document.querySelector('#packaging-fields'), document.querySelector('#final-service-fields'), document.querySelector('#final-options')].forEach(node => node.replaceChildren());
  const packageData = order.packages[0] || {};
  renderPackagePresets();
  for (const [key, label, factor] of packageUnits) {
    const usKey = key === 'weight_g' ? 'weight_oz' : key.replace('_mm', '_in');
    const rawValue = packageData[usKey] ?? (packageData[key] == null ? null : packageData[key] / factor);
    const value = rawValue == null ? '' : Math.ceil(rawValue);
    const input = field(packageFields, `package.${key}`, label, value, null, 'number');
    input.min = '1';
    input.step = '1';
    input.addEventListener('change', () => {
      if (input.value && Number(input.value) > 0) input.value = Math.ceil(Number(input.value));
    });
    input.required = true;
  }
  for (const [key, label] of Object.entries({ name: 'Contact name', company: 'Company', phone: 'Phone (optional)', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX or Texas)', postal: 'ZIP code', country: 'Country (US / CA)' })) {
    field(origin, `origin.${key}`, label, order.origin?.[key]);
  }
  renderShipperChoices();
  updateOriginSummary(true);
  const s = { ...(order.shipping == null ? workspaceSettings.shipping_defaults : order.shipping) };
  if (availableProviders.some(p => p.code === 'shipstation' && p.live_purchase_enabled)) s.provider = 'shipstation';
  else if (availableProviders.some(p => p.code === 'shipstation_test')) s.provider = 'shipstation_test';
  const providerSelect = document.createElement('input');
  providerSelect.type = 'hidden';
  providerSelect.name = 'shipping.provider';
  providerSelect.value = s.provider || 'fake';
  shipping.append(providerSelect);
  const carrierSelect = field(shipping, 'shipping.carrier_code', 'Carrier', s.carrier_code, []);
  const serviceSelect = field(shipping, 'shipping.service_code', 'Service', s.service_code, []);
  const packageSelect = field(shipping, 'shipping.package_code', 'Package type', s.package_code, []);
  const confirmationSelect = field(shipping, 'shipping.confirmation', 'Delivery confirmation', s.confirmation, []);
  async function refreshCatalog(restore = false) {
    const providerCode = providerSelect.value;
    carrierSelect.setOptions([]);
    serviceSelect.setOptions([]);
    packageSelect.setOptions([]);
    const modeInfo = availableProviders.find(p => p.code === providerCode);
    document.querySelector('#configuration-mode').textContent = providerCode === 'fake' ? 'Simulation only — not valid postage.' : providerCode === 'shipstation_test' ? 'Test mode · USPS test labels only · Not valid postage' : `ShipStation live account. Paid purchasing is ${modeInfo?.live_purchase_enabled ? 'enabled' : 'disabled in server configuration'}.`;
    document.querySelector('#create-label').textContent = providerCode === 'fake' ? 'Create simulated label' : providerCode === 'shipstation_test' ? 'Create label' : 'Buy shipping label';
    catalogLoaded = false;
    scheduleReadiness();
    try {
      const catalog = await api(`/api/providers/${providerCode}/carriers`);
      if (currentOrder?.id !== order.id || currentOrder?.version !== order.version || providerSelect.value !== providerCode) return;
      function options(control, rows, value) {
        control.setOptions(rows.map(row => [row.code, row.name]), value);
      }
      function updateCarrier(restoreValues = false) {
        const carrier = catalog.carriers.find(c => c.code === carrierSelect.value);
        const scope = order.recipient.country === 'CA' ? 'international' : 'domestic';
        options(serviceSelect, (carrier?.services || []).filter(s => s[scope] !== false), restoreValues ? s.service_code : '');
        options(packageSelect, (carrier?.packages || []).filter(p => p[scope] !== false), restoreValues ? s.package_code : '');
        const confirmation = confirmationSelect.value || (restoreValues ? s.confirmation : '');
        const confirmations = [['none', 'None'], ['delivery', 'Delivery confirmation'], ['signature', 'Signature'], ['adult_signature', 'Adult signature']];
        if (providerCode === 'fake' || carrierSelect.value.startsWith('fedex')) confirmations.push(['direct_signature', 'Direct signature (FedEx only)']);
        confirmationSelect.setOptions(confirmations, confirmation);
      }
      const savedCarrier = restore ? s.carrier_code : '';
      const defaultCarrier = providerCode === 'shipstation_test' ? 'stamps_com' : '';
      options(carrierSelect, catalog.carriers, catalog.carriers.some(c => c.code === savedCarrier) ? savedCarrier : defaultCarrier);
      updateCarrier(restore);
      carrierSelect.onchange = () => updateCarrier(false);
      applyComparedRate = rate => {
        const carrier = catalog.carriers.find(c => c.code === rate.carrier_code);
        const scope = order.recipient.country === 'CA' ? 'international' : 'domestic';
        const services = (carrier?.services || []).filter(s => s[scope] !== false);
        const packages = (carrier?.packages || []).filter(p => p[scope] !== false);
        if (!services.some(s => s.code === rate.service_code) || !packages.some(p => p.code === rate.package_code)) throw new Error('Service is no longer available. Reopen this order.');
        options(carrierSelect, catalog.carriers, rate.carrier_code);
        updateCarrier(false);
        options(serviceSelect, services, rate.service_code);
        options(packageSelect, packages, rate.package_code);
      };
      catalogLoaded = true;
      scheduleReadiness();
      if (providerCode !== 'fake') compareRates();
      else document.querySelector('#rates-status').textContent = 'Simulation has no carrier prices. Choose a simulated service in final review.';
    } catch (error) { document.querySelector('#validation-result').textContent = error.message; }
  }
  refreshCatalog(true);
  field(shipping, 'shipping.ship_date', 'Ship date', s.ship_date || order.default_ship_date, null, 'date');
  field(shipping, 'shipping.residential', 'Recipient address type', s.residential ?? true, [['true', 'Residential'], ['false', 'Commercial']]);
  const extras = document.createElement('details');
  extras.className = 'shipping-extras';
  const extrasSummary = message(extras, '', 'summary');
  const extraFields = document.createElement('div');
  extraFields.className = 'fields';
  extras.append(extraFields);
  document.querySelector('#final-options').append(extras);
  field(extraFields, 'shipping.insurance', 'Insurance', s.insurance, [['none', 'None'], ['carrier', 'Carrier']]);
  field(extraFields, 'shipping.insured_value', 'Insured value (USD, if insured)', s.insured_value);
  const addOns = [['saturday_delivery', 'Saturday delivery'], ['non_machinable', 'Non-machinable handling']];
  for (const [key, label] of addOns) {
    field(extraFields, `shipping.${key}`, label, String(s[key] ?? false), [['false', 'No'], ['true', 'Yes']]);
  }
  function summarizeExtras() {
    const selected = extraFields.querySelector('input[name="shipping.insurance"]:checked');
    const insuranceName = selected?.parentElement.textContent || 'Not selected';
    const enabled = addOns.filter(([key]) => extraFields.querySelector(`input[name="shipping.${key}"]:checked`)?.value === 'true').map(([, label]) => label);
    extrasSummary.textContent = `Insurance: ${insuranceName} · Additional services: ${enabled.join(', ') || 'None'}`;
  }
  extraFields.addEventListener('change', summarizeExtras);
  extras.open = !s.insurance || s.insurance !== 'none' || addOns.some(([key]) => s[key]);
  summarizeExtras();
  message(extraFields, 'Availability and extra charges depend on the carrier and account.');
  const catalogNote = message(shipping, availableProviders.some(p => p.code === 'shipstation') ? 'Carrier choices come from your connected account.' : 'Simulation only. Connect ShipStation credentials for real carrier choices.');
  catalogNote.className = 'field-note';
  for (const name of ['carrier_code', 'package_code']) {
    document.querySelector('#packaging-fields').append(shipping.querySelector(`[data-field="shipping.${name}"]`));
  }
  document.querySelector('#final-service-fields').append(shipping.querySelector('[data-field="shipping.service_code"]'));
  document.querySelector('#manual-service').open = providerSelect.value === 'fake';
  const canadian = order.recipient.country === 'CA';
  document.querySelector('#customs-heading').hidden = !canadian;
  customs.hidden = !canadian;
  document.querySelector('#customs-section').hidden = !canadian;
  if (canadian) {
    const choices = document.createElement('div');
    choices.className = 'fields customs-options';
    customs.append(choices);
    field(choices, 'shipping.duties_payer', 'Duties payer', s.duties_payer || 'recipient', [['recipient', 'Recipient']]);
    field(choices, 'customs.contents', 'Contents type', order.customs?.contents || 'merchandise', ['merchandise', 'documents', 'gift', 'returned_goods', 'sample'].map(code => [code, code.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())]));
    field(choices, 'customs.non_delivery', 'If undeliverable', order.customs?.non_delivery || 'return_to_sender', [['return_to_sender', 'Return to sender'], ['treat_as_abandoned', 'Treat as abandoned']]);
    order.items.forEach((item, index) => {
      const declaration = order.customs?.items?.find(d => d.item_id === item.id) || {};
      const itemFields = document.createElement('div');
      itemFields.className = 'fields customs-item';
      customs.append(itemFields);
      message(itemFields, `${item.sku} · quantity ${item.quantity}`, 'h4');
      for (const [key, label] of Object.entries({ description: 'Description', unit_value: 'Unit value', currency: 'Currency (USD)', country_of_origin: 'Origin (2 letters)', hs_code: 'HS code (6–10 digits)' })) {
        field(itemFields, `customs.${index}.${key}`, label, declaration[key]);
      }
    });
  }
}
function formValue(name) {
  const element = document.querySelector('#configuration-form').elements.namedItem(name);
  if (element?.type === 'radio') return element.checked ? element.value : '';
  return element?.value || '';
}
function configurationPayload() {
  const origin = {};
  for (const input of document.querySelectorAll('#origin-fields input')) origin[input.name.split('.')[1]] = input.value;
  const shipping = {};
  for (const input of document.querySelectorAll('#configuration-form input[name^="shipping."]')) {
    shipping[input.name.split('.')[1]] = formValue(input.name);
  }
  for (const key of ['saturday_delivery', 'non_machinable']) shipping[key] = shipping[key] === 'true';
  shipping.contains_alcohol = false;
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
  const packageMeasurements = { id: currentOrder.packages[0]?.id, us_units: {} };
  for (const [key, , factor] of packageUnits) {
    const input = document.querySelector('#configuration-form').elements.namedItem(`package.${key}`);
    // Displayed whole US units are also used for storage and carrier requests.
    const value = Math.ceil(Number(input.value));
    const usKey = key === 'weight_g' ? 'weight_oz' : key.replace('_mm', '_in');
    packageMeasurements.us_units[usKey] = value;
    packageMeasurements[key] = value > 0 ? Math.ceil(value * factor - 1e-9) : value;
  }
  return { version: currentOrder.version, origin, shipping, customs, package: packageMeasurements };
}
async function saveConfiguration() {
  const order = await api(`/api/orders/${currentOrder.id}`, { method: 'PATCH', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify(configurationPayload()) });
  await showConfiguration(order);
  return order;
}
document.querySelector('#configuration-form').addEventListener('submit', event => event.preventDefault());
document.querySelector('#configuration-form').addEventListener('input', scheduleReadiness);
document.querySelector('#configuration-form').addEventListener('change', scheduleReadiness);

// Keep the request token until success/failure is known; an uncertain request must not be repurchased.
const purchaseTokens = new Map();
document.querySelector('#create-label').addEventListener('click', async event => {
  if (!currentOrder || labelRequestInFlight || !shipmentReady || !ratePurchaseAllowed()) return;
  labelRequestInFlight = true;
  const button = event.currentTarget;
  button.disabled = true;
  const target = document.querySelector('#purchase-result');
  try {
    const selected = formValue('shipping.provider');
    if (selected === 'shipstation' && !window.confirm(`Buy a real shipping label for order ${currentOrder.wms_order_no}? ${selectedRate ? `Selected: ${selectedRate.service_name}, estimated ${rateMoney(selectedRate.total_minor)} USD (excludes insurance and add-ons). ` : ''}This charges your connected carrier account; actual cost may differ.`)) return;
    const order = await saveConfiguration();
    const key = `${order.id}:${order.version}`;
    if (!purchaseTokens.has(key)) purchaseTokens.set(key, crypto.randomUUID());
    const attempt = await api(`/api/orders/${order.id}/label-attempts`, {
      method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: order.version, package_id: order.packages[0].id, request_token: purchaseTokens.get(key), confirm_purchase: true, repeat_test: selected === 'shipstation_test' })
    });
    if (attempt.mode === 'test' && attempt.state === 'purchased') {
      purchaseTokens.delete(key);
      button.textContent = 'Create another USPS test label';
    }
    target.textContent = ` ${attempt.mode === 'simulation' ? 'SIMULATION — NOT VALID POSTAGE.' : attempt.mode === 'test' ? 'USPS TEST LABEL — NOT VALID POSTAGE.' : 'ShipStation purchase.'} Attempt ${attempt.id}: ${attempt.state}. ${attempt.labels.map(l => l.tracking_number).join(', ')}`;
    for (const label of attempt.labels) {
      for (const [kind, title] of [['print', 'Label PDF / thermal print'], ['letter', 'Letter PDF'], ['original', 'Original carrier PDF']]) {
        const link = message(target, title, 'a');
        link.href = `/api/labels/${label.id}/pdf?kind=${kind}`;
        link.target = '_blank'; link.rel = 'noopener';
      }
      renderVoidAction(target, { ...label, label_id: label.id, order_id: order.id, wms_order_no: order.wms_order_no });
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    await loadOrders();
  } catch (error) { target.textContent = error.message; }
  finally {
    labelRequestInFlight = false;
    updateCreateLabel();
  }
});

const addressLabels = { name: 'Contact name', company: 'Company', phone: 'Phone (optional)', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX or Texas)', postal: 'ZIP code', country: 'Country (US / CA)' };
let shipperContacts = [];
let editingContactId = null;
function editContact(contact = null) {
  editingContactId = contact?.id || null;
  document.querySelector('#contact-form-heading').textContent = contact ? 'Edit contact' : 'Add contact';
  const container = document.querySelector('#contact-fields');
  container.replaceChildren();
  field(container, 'label', 'Saved contact name', contact?.label).required = true;
  for (const [key, label] of Object.entries(addressLabels)) {
    field(container, key, label, contact?.address[key] || (!contact && key === 'country' ? 'US' : ''));
  }
}
function renderShipperChoices() {
  const container = document.querySelector('#shipper-choices');
  container.replaceChildren();
  if (!shipperContacts.length) {
    message(container, 'No saved contacts yet. Add a shipper contact in Settings, or enter details below.');
    const button = message(container, 'Add a contact in Settings', 'button');
    button.type = 'button';
    button.onclick = () => openTab('settings');
    return;
  }
  const originInputs = [...document.querySelectorAll('#origin-fields input')];
  if (originInputs.every(input => !input.value.trim())) {
    const defaultContact = shipperContacts.find(contact => contact.is_default) || (shipperContacts.length === 1 ? shipperContacts[0] : null);
    if (defaultContact) {
      for (const input of originInputs) input.value = defaultContact.address[input.name.split('.')[1]] || '';
      updateOriginSummary(true);
      scheduleReadiness();
    }
  }
  const matches = shipperContacts.find(contact => Object.keys(addressLabels).every(key =>
    (document.querySelector('#configuration-form').elements.namedItem(`origin.${key}`)?.value || '') === (contact.address[key] || '')));
  const choice = field(container, 'saved_shipper', 'Saved shipper contact', matches?.id || '', shipperContacts.map(c => [c.id, c.label]));
  choice.onchange = () => {
    const contact = shipperContacts.find(c => c.id === choice.value);
    if (!contact) return;
    for (const key of Object.keys(addressLabels)) {
      document.querySelector('#configuration-form').elements.namedItem(`origin.${key}`).value = contact.address[key] || '';
    }
    updateOriginSummary(true);
    scheduleReadiness();
  };
  // A manually edited address is no longer an exact copy of a saved contact.
  document.querySelectorAll('#origin-fields input').forEach(input => {
    input.oninput = () => {
      container.querySelectorAll('input[type="radio"]').forEach(radio => { radio.checked = false; });
      updateOriginSummary();
    };
  });
}
async function loadContacts() {
  shipperContacts = await api('/api/shipper-contacts');
  const list = document.querySelector('#contact-list');
  list.replaceChildren();
  if (!shipperContacts.length) message(list, 'No saved shipper contacts. Add your first contact below.');
  for (const contact of shipperContacts) {
    const article = document.createElement('article');
    message(article, `${contact.label}${contact.is_default ? ' · Default shipper' : ''}`, 'h3');
    if (!contact.is_default) {
      const makeDefault = message(article, 'Use as default shipper', 'button');
      makeDefault.type = 'button';
      makeDefault.onclick = async () => {
        makeDefault.disabled = true;
        try {
          await api(`/api/shipper-contacts/${contact.id}/default`, { method: 'PUT', headers: { 'X-CSRF-Token': csrf } });
          await loadContacts();
          document.querySelector('#contact-status').textContent = 'Default shipper updated. Orders with saved shipper details keep their address.';
        } catch (error) { document.querySelector('#contact-status').textContent = error.message; makeDefault.disabled = false; }
      };
    }
    message(article, [contact.address.name, contact.address.company, contact.address.phone, contact.address.address1, contact.address.address2, contact.address.city, contact.address.state, contact.address.postal, contact.address.country].filter(Boolean).join(' · '));
    const edit = message(article, 'Edit', 'button');
    edit.type = 'button';
    edit.onclick = () => { editContact(contact); document.querySelector('#contact-form').elements.namedItem('label').focus(); };
    const remove = message(article, 'Delete', 'button');
    remove.type = 'button';
    remove.onclick = async () => {
      if (!window.confirm(`Delete saved contact “${contact.label}”? Saved orders keep their shipper details.`)) return;
      try {
        await api(`/api/shipper-contacts/${contact.id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } });
        if (editingContactId === contact.id) editContact();
        await loadContacts();
        document.querySelector('#contact-status').textContent = 'Contact deleted. Saved orders are unchanged.';
      } catch (error) { document.querySelector('#contact-status').textContent = error.message; }
    };
    list.append(article);
  }
  if (currentOrder) renderShipperChoices();
}
document.querySelector('#new-contact').onclick = () => editContact();
document.querySelector('#contact-form').addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const contactId = editingContactId;
  const payload = { label: form.elements.namedItem('label').value, address: Object.fromEntries(Object.keys(addressLabels).map(key => [key, form.elements.namedItem(key).value])) };
  button.disabled = true;
  try {
    await api(`/api/shipper-contacts${contactId ? `/${contactId}` : ''}`, { method: contactId ? 'PUT' : 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    editContact();
    await loadContacts();
    document.querySelector('#contact-status').textContent = 'Contact saved. The default shipper is applied automatically to orders without shipper details.';
  } catch (error) { document.querySelector('#contact-status').textContent = error.message; }
  finally { button.disabled = false; }
});
editContact();
const contactsReady = loadContacts().catch(error => { document.querySelector('#contact-status').textContent = error.message; });

function updateOriginSummary(collapse = false) {
  const value = key => document.querySelector('#configuration-form').elements.namedItem(`origin.${key}`)?.value.trim() || '';
  const lines = [
    [value('name'), value('company')].filter(Boolean).join(' · '),
    [value('address1'), value('address2')].filter(Boolean).join(', '),
    [value('city'), value('state'), value('postal'), value('country')].filter(Boolean).join(' '),
    value('phone'),
  ].filter(Boolean);
  document.querySelector('#origin-summary').textContent = lines.join('\n') || 'Choose a saved shipper or enter the return address.';
  const complete = ['name', 'address1', 'city', 'state', 'postal', 'country'].every(key => value(key));
  if (collapse) document.querySelector('#origin-details').open = !complete;
}
document.querySelector('#origin-fields').addEventListener('input', () => updateOriginSummary());

function renderVoidAction(container, row) {
  message(container, row.void_status === 'voided' ? 'Removed locally' : '', 'span');
  if (row.void_status === 'voided') return;
  const button = message(container, 'Remove label', 'button');
  button.type = 'button';
  button.onclick = async () => {
    if (!window.confirm(`Remove label ${row.tracking_number || row.label_id} for order ${row.wms_order_no} from this app? ShipStation postage stays unchanged; this does not cancel postage or request a refund.`)) return;
    button.disabled = true;
    try {
      const result = await api(`/api/labels/${row.label_id}/void`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_void: true })
      });
      window.alert('Label removed locally. ShipStation was not changed.');
      container.replaceChildren();
      message(container, 'Label removed locally. ShipStation postage is unchanged.');
      if (result.void_status === 'voided' && currentOrder?.id === row.order_id) {
        for (const key of purchaseTokens.keys()) if (key.startsWith(`${row.order_id}:`)) purchaseTokens.delete(key);
      }
      await loadOrders();
    } catch (error) { window.alert(error.message); }
    finally { button.disabled = false; }
  };
}
