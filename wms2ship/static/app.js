const csrf = document.querySelector('meta[name="csrf-token"]').content;
const status = document.querySelector('#status');
const orders = document.querySelector('#orders');
const results = document.querySelector('#import-result');

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed.');
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
        document.querySelector('#order-preview').textContent = JSON.stringify(order, null, 2);
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
