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
        await showConfiguration(order);
        document.querySelector('#no-order-selected').hidden = true;
        document.querySelector('#preview-panel').hidden = false;
        openTab('orders');
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
    document.dispatchEvent(new Event('wms-import-complete'));
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
loadOrders().catch(error => { status.textContent = error.message; });

let currentOrder;
let labelRequestInFlight = false;
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
  wrapper.append(input);
  parent.append(wrapper);
  return input;
}
async function showConfiguration(order) {
  await providersReady;
  await contactsReady;
  currentOrder = order;
  document.querySelector('#order-preview').textContent = JSON.stringify(order, null, 2);
  document.querySelector('#order-summary').textContent = `${order.wms_order_no} · ${order.recipient.country} · ${order.packages[0]?.weight_g || '?'} g`;
  document.querySelector('#validation-result').replaceChildren();
  const origin = document.querySelector('#origin-fields');
  const shipping = document.querySelector('#shipping-fields');
  const customs = document.querySelector('#customs-fields');
  [origin, shipping, customs].forEach(node => node.replaceChildren());
  for (const [key, label] of Object.entries({ name: 'Contact name', company: 'Company', phone: 'Phone', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX or Texas)', postal: 'ZIP code', country: 'Country (US or United States)' })) {
    field(origin, `origin.${key}`, label, order.origin?.[key]);
  }
  renderShipperChoices();
  updateOriginSummary(true);
  const s = { ...(order.shipping || {}) };
  if (availableProviders.some(p => p.code === 'shipstation_test')) s.provider = 'shipstation_test';
  const providerSelect = field(shipping, 'shipping.provider', 'Shipping provider', s.provider || 'fake', availableProviders.filter(p => availableProviders.some(item => item.code === 'shipstation_test') ? p.code === 'shipstation_test' : p.code === 'fake').map(p => [p.code, p.mode === 'test' ? 'ShipStation development — test labels' : 'Simulation — no postage']));
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
    document.querySelector('#configuration-mode').textContent = providerCode === 'fake' ? 'Simulation only — not valid postage.' : providerCode === 'shipstation_test' ? 'Development mode: every label uses ShipStation testLabel: true. Works with any order number; labels are not valid postage. V1 supports USPS test labels.' : `ShipStation live account. Paid purchasing is ${modeInfo?.live_purchase_enabled ? 'enabled' : 'disabled in server configuration'}.`;
    document.querySelector('#create-label').textContent = providerCode === 'fake' ? 'Create simulated label' : providerCode === 'shipstation_test' ? 'Create label' : 'Buy shipping label';
    document.querySelector('#create-label').disabled = labelRequestInFlight || (providerCode === 'shipstation' && !modeInfo?.live_purchase_enabled);
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
    } catch (error) { document.querySelector('#validation-result').textContent = error.message; }
  }
  providerSelect.onchange = () => refreshCatalog(false);
  refreshCatalog(true);
  field(shipping, 'shipping.ship_date', 'Ship date', s.ship_date, null, 'date');
  field(shipping, 'shipping.residential', 'Recipient address type', s.residential, [['true', 'Residential'], ['false', 'Commercial']]);
  const extras = document.createElement('details');
  extras.className = 'shipping-extras';
  const extrasSummary = message(extras, '', 'summary');
  const extraFields = document.createElement('div');
  extraFields.className = 'fields';
  extras.append(extraFields);
  shipping.append(extras);
  field(extraFields, 'shipping.insurance', 'Insurance', s.insurance, [['none', 'None'], ['carrier', 'Carrier'], ['shipsurance', 'Shipsurance'], ['xcover', 'XCover'], ['parcelguard', 'ParcelGuard'], ['provider', 'Other insurance (billed outside ShipStation)']]);
  field(extraFields, 'shipping.insured_value', 'Insured value (USD, if insured)', s.insured_value);
  const addOns = [['saturday_delivery', 'Saturday delivery'], ['non_machinable', 'Non-machinable handling'], ['contains_alcohol', 'Contains alcohol']];
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
  message(extraFields, 'Availability and extra charges depend on the carrier and account. Other insurance is billed outside ShipStation.');
  const catalogNote = message(shipping, availableProviders.some(p => p.code === 'shipstation') ? 'Carrier choices come from your connected account.' : 'Simulation only. Connect ShipStation credentials for real carrier choices.');
  catalogNote.className = 'field-note';
  const canadian = order.recipient.country === 'CA';
  document.querySelector('#customs-heading').hidden = !canadian;
  customs.hidden = !canadian;
  document.querySelector('#customs-section').hidden = !canadian;
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
  const element = document.querySelector('#configuration-form').elements.namedItem(name);
  if (element?.type === 'radio') return element.checked ? element.value : '';
  return element?.value || '';
}
async function saveConfiguration() {
  if (!currentOrder) return;
  const origin = {};
  for (const input of document.querySelectorAll('#origin-fields input')) origin[input.name.split('.')[1]] = input.value;
  const shipping = {};
  for (const input of document.querySelectorAll('#shipping-fields input')) {
    shipping[input.name.split('.')[1]] = formValue(input.name);
  }
  for (const key of ['saturday_delivery', 'non_machinable', 'contains_alcohol']) shipping[key] = shipping[key] === 'true';
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
  await showConfiguration(order);
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
    if (result.valid) message(target, result.mode === 'simulation' ? 'Ready for a simulated purchase — not usable postage.' : result.mode === 'test' ? 'Ready for a USPS test label — not valid postage.' : 'Required fields are complete. Review the shipment before buying postage.');
    for (const issue of result.issues) message(target, `${issue.field}: ${issue.message}`);
  } catch (error) { target.textContent = error.message; }
});

// Keep the request token until success/failure is known; an uncertain request must not be repurchased.
const purchaseTokens = new Map();
document.querySelector('#create-label').addEventListener('click', async event => {
  if (!currentOrder || labelRequestInFlight) return;
  labelRequestInFlight = true;
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
      body: JSON.stringify({ version: order.version, package_id: order.packages[0].id, request_token: purchaseTokens.get(key), confirm_purchase: true, repeat_test: selected === 'shipstation_test' })
    });
    if (attempt.mode === 'test' && attempt.state === 'purchased') {
      purchaseTokens.delete(key);
      button.textContent = 'Create another USPS test label';
    }
    await loadHistory(true);
    target.textContent = ` ${attempt.mode === 'simulation' ? 'SIMULATION — NOT VALID POSTAGE.' : attempt.mode === 'test' ? 'USPS TEST LABEL — NOT VALID POSTAGE.' : 'ShipStation purchase.'} Attempt ${attempt.id}: ${attempt.state}. ${attempt.labels.map(l => l.tracking_number).join(', ')}`;
  } catch (error) { target.textContent = error.message; }
  finally {
    labelRequestInFlight = false;
    const provider = formValue('shipping.provider');
    button.disabled = (provider === 'shipstation' && !availableProviders.find(p => p.code === 'shipstation')?.live_purchase_enabled);
  }
});

let historyOffset = 0;
let historyQuery = new URLSearchParams();
let historyBusy = false;
async function loadHistory(reset = false) {
  if (historyBusy) return;
  historyBusy = true;
  const target = document.querySelector('#history');
  const feedback = document.querySelector('#history-status');
  const more = document.querySelector('#more-history');
  const refresh = document.querySelector('#refresh-history');
  more.disabled = refresh.disabled = true;
  document.querySelector('#clear-history-filters').disabled = true;
  feedback.textContent = 'Loading history…';
  try {
    const query = reset ? new URLSearchParams(new FormData(document.querySelector('#history-filters'))) : new URLSearchParams(historyQuery);
    if (reset) {
      for (const [key, value] of [...query.entries()]) {
        if (!value.trim()) query.delete(key);
        else if (key === 'start' || key === 'end') query.set(key, new Date(value).toISOString());
      }
    }
    query.set('offset', reset ? 0 : historyOffset);
    const rows = await api(`/api/history?${query}`);
    if (reset) {
      historyOffset = 0;
      target.replaceChildren();
      query.delete('offset');
      historyQuery = query;
    }
    if (!rows.length && historyOffset === 0) {
      const cell = message(message(target, '', 'tr'), 'No labels or attempts match these filters.', 'td');
      cell.colSpan = 10;
    }
    for (const row of rows) {
      const tr = message(target, '', 'tr');
      message(tr, row.wms_order_no, 'td');
      const created = message(tr, new Date(row.created_at).toLocaleString(), 'td');
      created.title = row.created_at;
      for (const value of [row.mode.toUpperCase(), row.state, row.provider_code, row.tracking_number || '—', row.charge_minor == null ? 'Not recorded' : `${(row.charge_minor / 100).toFixed(2)} ${row.currency}`, row.error_code || '—']) message(tr, value, 'td');
      const links = message(tr, '', 'td');
      if (row.label_id) {
        for (const kind of ['letter', 'original']) {
          const link = message(links, kind === 'letter' ? 'Letter PDF / print' : 'Original PDF', 'a');
          link.href = `/api/labels/${row.label_id}/pdf?kind=${kind}`;
          link.target = '_blank'; link.rel = 'noopener';
        }
      } else links.textContent = '—';
      message(tr, row.attempt_id, 'td');
    }
    historyOffset += rows.length;
    more.hidden = rows.length < 50;
    feedback.textContent = `Showing ${historyOffset} matching records.${more.hidden ? '' : ' Load more for older matches.'}`;
  } catch (error) { feedback.textContent = error.message; }
  finally {
    historyBusy = false; more.disabled = refresh.disabled = false;
    document.querySelector('#clear-history-filters').disabled = false;
  }
}
document.querySelector('#history-filters').addEventListener('submit', event => { event.preventDefault(); loadHistory(true); });
document.querySelector('#history-filters').addEventListener('input', () => { document.querySelector('#history-status').textContent = 'Filters changed. Apply filters to update the table.'; });
document.querySelector('#clear-history-filters').addEventListener('click', () => { document.querySelector('#history-filters').reset(); loadHistory(true); });
document.querySelector('#more-history').addEventListener('click', () => loadHistory(false));
document.querySelector('#tab-history').addEventListener('click', () => loadHistory(true));
loadHistory(true);

const addressLabels = { name: 'Contact name', company: 'Company', phone: 'Phone', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX or Texas)', postal: 'ZIP code', country: 'Country (US or United States)' };
let shipperContacts = [];
let editingContactId = null;
function editContact(contact = null) {
  editingContactId = contact?.id || null;
  document.querySelector('#contact-form-heading').textContent = contact ? 'Edit contact' : 'Add contact';
  const container = document.querySelector('#contact-fields');
  container.replaceChildren();
  field(container, 'label', 'Saved contact name', contact?.label).required = true;
  for (const [key, label] of Object.entries(addressLabels)) {
    field(container, key, label, contact?.address[key] || '');
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
    document.querySelector('#validation-result').textContent = 'Shipper contact applied. Save configuration to keep it on this order.';
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
    message(article, contact.label, 'h3');
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
    document.querySelector('#contact-status').textContent = 'Contact saved. Select it in Shipping details to use it on an order.';
  } catch (error) { document.querySelector('#contact-status').textContent = error.message; }
  finally { button.disabled = false; }
});
editContact();
const contactsReady = loadContacts().catch(error => { document.querySelector('#contact-status').textContent = error.message; });

const reviewFields = document.querySelector('#review-filter-fields');
field(reviewFields, 'start', 'Activity from (UTC)', '', null, 'date');
field(reviewFields, 'end', 'Activity through (UTC)', '', null, 'date');
field(reviewFields, 'search', 'Order, tracking, recipient, or shipper');
field(reviewFields, 'state', 'Label status', 'all', ['all', 'not_started', 'prepared', 'sending', 'purchased', 'failed', 'uncertain'].map(code => [code, code.replaceAll('_', ' ')]));
field(reviewFields, 'mode', 'Postage mode', 'all', [['all', 'All'], ['live', 'Live'], ['simulation', 'Simulation'], ['test', 'USPS test labels'], ['unassigned', 'No attempt']]);
let reviewQuery = new URLSearchParams();
let reviewOffset = 0;
let reviewBusy = false;
const reviewColumns = [['wms_order_no', 'WMS order'], ['state', 'Label status'], ['mode', 'Mode'], ['created_at', 'Activity (UTC)'], ['shipper', 'Shipper'], ['recipient', 'Recipient'], ['country', 'Destination'], ['carrier', 'Carrier'], ['service', 'Service'], ['tracking_number', 'Tracking'], ['charge_minor', 'Charge'], ['error_code', 'Exception']];
for (const [, title] of reviewColumns) {
  const th = message(document.querySelector('#review-table thead tr'), title, 'th');
  th.scope = 'col';
}
message(document.querySelector('#review-table thead tr'), 'Label PDF', 'th').scope = 'col';
async function loadReview(reset = true) {
  if (reviewBusy) return;
  reviewBusy = true;
  const target = document.querySelector('#review-status');
  const submit = document.querySelector('#review-filters button[type="submit"]');
  const more = document.querySelector('#review-more');
  submit.disabled = true;
  more.disabled = true;
  target.textContent = 'Loading shipment review…';
  try {
    const query = reset ? new URLSearchParams(new FormData(document.querySelector('#review-filters'))) : new URLSearchParams(reviewQuery);
    for (const [key, value] of [...query.entries()]) if (!value) query.delete(key);
    query.set('offset', reset ? 0 : reviewOffset);
    const data = await api(`/api/review?${query}`);
    const body = document.querySelector('#review-table tbody');
    if (reset) {
      body.replaceChildren();
      reviewOffset = 0;
      query.delete('offset');
      reviewQuery = query;
      document.querySelector('#download-report').href = `/api/review/report.xlsx?${reviewQuery}`;
      const summary = document.querySelector('#review-summary');
      summary.replaceChildren();
      for (const [label, value] of [['Orders', data.summary.orders], ['Label purchases', data.summary.purchased], ['Not started', data.summary.not_started], ['Exceptions', data.summary.exceptions]]) {
        const card = message(summary, '', 'div');
        message(card, value, 'strong');
        message(card, label, 'span');
      }
      for (const charge of data.summary.charges) {
        message(summary, `${charge.mode.toUpperCase()} · ${(charge.minor / 100).toFixed(2)} ${charge.currency}`, 'p');
      }
      if (data.summary.unknown_charges) message(summary, `${data.summary.unknown_charges} purchased label(s) have no recorded charge.`, 'p');
      if (!data.total) {
        const row = message(body, '', 'tr');
        const cell = message(row, 'No shipments or orders match these filters.', 'td');
        cell.colSpan = reviewColumns.length + 1;
      }
    }
    for (const row of data.rows) {
      const tr = message(body, '', 'tr');
      for (const [key] of reviewColumns) {
        let value = row[key] ?? '—';
        if (key === 'charge_minor') value = row.charge_minor == null ? 'Not recorded' : `${(row.charge_minor / 100).toFixed(2)} ${row.currency}`;
        if (key === 'state') value = value.replaceAll('_', ' ');
        message(tr, value || '—', 'td');
      }
      const pdf = message(tr, '', 'td');
      if (row.label_id) {
        const link = message(pdf, 'Open / print', 'a');
        link.href = `/api/labels/${row.label_id}/pdf`;
        link.target = '_blank';
        link.rel = 'noopener';
      }
    }
    reviewOffset += data.rows.length;
    more.hidden = reviewOffset >= data.total;
    target.textContent = `Showing ${reviewOffset} of ${data.total} records. Excel downloads all matching records, including those on later pages.`;
  } catch (error) { target.textContent = error.message; }
  finally { reviewBusy = false; submit.disabled = false; more.disabled = false; }
}
document.querySelector('#review-filters').addEventListener('submit', event => { event.preventDefault(); loadReview(true); });
document.querySelector('#review-filters').addEventListener('change', () => {
  document.querySelector('#review-status').textContent = 'Filters changed. Apply filters to update the dashboard and Excel report.';
});
document.querySelector('#review-more').onclick = () => loadReview(false);
document.querySelector('#tab-review').addEventListener('click', () => loadReview(true));
loadReview(true);


function updateOriginSummary(collapse = false) {
  const value = key => document.querySelector('#configuration-form').elements.namedItem(`origin.${key}`)?.value.trim() || '';
  const lines = [
    [value('name'), value('company')].filter(Boolean).join(' · '),
    [value('address1'), value('address2')].filter(Boolean).join(', '),
    [value('city'), value('state'), value('postal'), value('country')].filter(Boolean).join(' '),
    value('phone'),
  ].filter(Boolean);
  document.querySelector('#origin-summary').textContent = lines.join('\n') || 'Choose a saved shipper or enter the return address.';
  const complete = ['name', 'phone', 'address1', 'city', 'state', 'postal', 'country'].every(key => value(key));
  if (collapse) document.querySelector('#origin-details').open = !complete;
}
document.querySelector('#origin-fields').addEventListener('input', () => updateOriginSummary());
