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
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
});
loadOrders().catch(error => { status.textContent = error.message; });

let currentOrder;
let availableProviders = [{code: 'fake', mode: 'simulation', live_purchase_enabled: false}];
const providersReady = api('/api/providers').then(data => {
  availableProviders = data;
  status.textContent = data.some(p => p.mode === 'live') ? 'Workspace ready. ShipStation credentials configured; verify account access in the order form.' : 'Workspace ready. Simulation provider available.';
}).catch(error => { status.textContent = error.message; });
function field(parent, name, label, value = '', options = null, type = 'text') {
  if (options) {
    const group = document.createElement('fieldset');
    group.className = 'radio-field';
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
  for (const [key, label] of Object.entries({ name: 'Contact name', company: 'Company', phone: 'Phone', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX)', postal: 'ZIP code', country: 'Country (US)' })) {
    field(origin, `origin.${key}`, label, order.origin?.[key]);
  }
  renderShipperChoices();
  const s = order.shipping || {};
  const providerSelect = field(shipping, 'shipping.provider', 'Shipping provider', s.provider || 'fake', availableProviders.map(p => [p.code, p.mode === 'simulation' ? 'Simulation — no postage' : 'ShipStation V1 — live account']));
  const carrierSelect = field(shipping, 'shipping.carrier_code', 'Carrier', s.carrier_code, []);
  const serviceSelect = field(shipping, 'shipping.service_code', 'Service', s.service_code, []);
  const packageSelect = field(shipping, 'shipping.package_code', 'Package type', s.package_code, []);
  async function refreshCatalog(restore = false) {
    const providerCode = providerSelect.value;
    carrierSelect.setOptions([]);
    serviceSelect.setOptions([]);
    packageSelect.setOptions([]);
    const modeInfo = availableProviders.find(p => p.code === providerCode);
    document.querySelector('#configuration-mode').textContent = providerCode === 'fake' ? 'Simulation only — not valid postage.' : `ShipStation live account. Paid purchasing is ${modeInfo?.live_purchase_enabled ? 'enabled' : 'disabled in server configuration'}.`;
    document.querySelector('#create-label').textContent = providerCode === 'fake' ? 'Create simulated label' : 'Buy shipping label';
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

const addressLabels = { name: 'Contact name', company: 'Company', phone: 'Phone', address1: 'Street address', address2: 'Address line 2', city: 'City (Katy)', state: 'State (TX)', postal: 'ZIP code', country: 'Country (US)' };
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
    document.querySelector('#validation-result').textContent = 'Shipper contact applied. Save configuration to keep it on this order.';
  };
  // A manually edited address is no longer an exact copy of a saved contact.
  document.querySelectorAll('#origin-fields input').forEach(input => {
    input.oninput = () => container.querySelectorAll('input[type="radio"]').forEach(radio => { radio.checked = false; });
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
