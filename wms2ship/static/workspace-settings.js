let workspaceSettings = {shipping_defaults: {}, package_templates: [], connection: {}};
let editingPackageTemplate = null;
let defaultsCatalog = null;
const defaultsForm = document.querySelector('#shipping-defaults-form');
const templateForm = document.querySelector('#package-template-form');
const connectionForm = document.querySelector('#connection-form');

function selectChoices(select, rows, value) {
  select.replaceChildren(new Option('Choose per order', ''));
  for (const row of rows) select.add(new Option(row.name, row.code));
  if (value && !rows.some(row => row.code === value)) select.add(new Option(`${value} (saved)`, value));
  select.value = value || '';
}

function renderDefaultCatalog(saved = workspaceSettings.shipping_defaults) {
  const carriers = defaultsCatalog?.carriers || [];
  selectChoices(defaultsForm.elements.carrier_code, carriers, saved.carrier_code);
  const carrier = carriers.find(row => row.code === saved.carrier_code);
  selectChoices(defaultsForm.elements.service_code, carrier?.services || [], saved.service_code);
  selectChoices(defaultsForm.elements.package_code, carrier?.packages || [], saved.package_code);
}

function renderPackagePresets(selected = '') {
  const select = document.querySelector('#package-preset');
  select.replaceChildren(new Option('Keep current dimensions', ''));
  for (const row of workspaceSettings.package_templates) select.add(new Option(
    `${row.name} · ${row.length_in} × ${row.width_in} × ${row.height_in} in`, row.id
  ));
  select.value = selected;
}

function editPackageTemplate(row = null) {
  editingPackageTemplate = row?.id || null;
  document.querySelector('#package-template-heading').textContent = row ? 'Edit package template' : 'Add package template';
  for (const name of ['name', 'length_in', 'width_in', 'height_in']) templateForm.elements[name].value = row?.[name] ?? '';
}

function applyWorkspaceSettings(data) {
  workspaceSettings = data;
  const connection = data.connection;
  document.querySelector('#connection-summary').textContent = connection.last_test
    ? `${connection.last_test.message} Tested ${new Date(connection.last_test.checked_at).toLocaleString()}.`
    : connection.configured ? 'Credentials configured. Connection has not been tested in this session.' : 'No ShipStation credentials configured.';
  for (const name of ['residential', 'insurance', 'confirmation']) defaultsForm.elements[name].value = String(data.shipping_defaults[name]);
  renderDefaultCatalog();
  const list = document.querySelector('#package-template-list');
  list.replaceChildren();
  if (!data.package_templates.length) message(list, 'No package templates yet. Add your common boxes below.');
  for (const row of data.package_templates) {
    const item = message(list, '', 'div');
    item.className = 'package-template-row';
    message(item, `${row.name} · ${row.length_in} × ${row.width_in} × ${row.height_in} in`, 'strong');
    const edit = message(item, 'Edit', 'button');
    edit.type = 'button';
    edit.onclick = () => editPackageTemplate(row);
    const remove = message(item, 'Delete', 'button');
    remove.type = 'button';
    remove.onclick = async () => {
      if (!window.confirm(`Delete package template “${row.name}”?`)) return;
      try {
        applyWorkspaceSettings(await api(`/api/settings/package-templates/${row.id}`, {method: 'DELETE', headers: {'X-CSRF-Token': csrf}}));
        if (editingPackageTemplate === row.id) editPackageTemplate();
      } catch (error) { document.querySelector('#package-template-status').textContent = error.message; }
    };
  }
  renderPackagePresets();
}

const workspaceSettingsReady = api('/api/settings').then(applyWorkspaceSettings).catch(error => {
  document.querySelector('#connection-summary').textContent = `Settings unavailable: ${error.message}`;
});

document.querySelector('#package-preset').addEventListener('change', event => {
  const row = workspaceSettings.package_templates.find(row => row.id === event.target.value);
  if (!row) return;
  for (const key of ['length', 'width', 'height']) document.querySelector('#configuration-form').elements.namedItem(`package.${key}_mm`).value = row[`${key}_in`];
  scheduleReadiness();
});

document.querySelector('#load-default-carriers').onclick = async event => {
  const status = document.querySelector('#shipping-defaults-status');
  event.target.disabled = true;
  try {
    const providers = await api('/api/providers');
    const provider = providers.some(row => row.code === 'shipstation') ? 'shipstation' : 'fake';
    const saved = Object.fromEntries(new FormData(defaultsForm));
    defaultsCatalog = await api(`/api/providers/${provider}/carriers`);
    renderDefaultCatalog(saved);
    status.textContent = provider === 'fake' ? 'Simulation choices only. Connect ShipStation for real carriers.' : 'Carrier choices loaded from ShipStation.';
  } catch (error) { status.textContent = error.message; }
  finally { event.target.disabled = false; }
};
defaultsForm.elements.carrier_code.onchange = () => {
  const carrier = defaultsCatalog?.carriers.find(row => row.code === defaultsForm.elements.carrier_code.value);
  selectChoices(defaultsForm.elements.service_code, carrier?.services || [], '');
  selectChoices(defaultsForm.elements.package_code, carrier?.packages || [], '');
};
defaultsForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = defaultsForm.querySelector('button[type="submit"]');
  button.disabled = true;
  const payload = Object.fromEntries(new FormData(defaultsForm));
  payload.residential = payload.residential === 'true';
  try {
    applyWorkspaceSettings(await api('/api/settings/shipping-defaults', {method: 'PUT', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify(payload)}));
    document.querySelector('#shipping-defaults-status').textContent = 'Defaults saved. Used for orders without saved shipping settings.';
  } catch (error) { document.querySelector('#shipping-defaults-status').textContent = error.message; }
  finally { button.disabled = false; }
});

templateForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = templateForm.querySelector('button[type="submit"]');
  button.disabled = true;
  const payload = Object.fromEntries(new FormData(templateForm));
  for (const key of ['length_in', 'width_in', 'height_in']) payload[key] = Number(payload[key]);
  try {
    applyWorkspaceSettings(await api(`/api/settings/package-templates${editingPackageTemplate ? `/${editingPackageTemplate}` : ''}`, {method: editingPackageTemplate ? 'PUT' : 'POST', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify(payload)}));
    editPackageTemplate();
    document.querySelector('#package-template-status').textContent = 'Package template saved. Dimensions rounded up to whole inches.';
  } catch (error) { document.querySelector('#package-template-status').textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector('#new-package-template').onclick = () => editPackageTemplate();

async function connectShipStation(save) {
  const status = document.querySelector('#connection-status');
  const buttons = [...connectionForm.querySelectorAll('button')];
  buttons.forEach(button => { button.disabled = true; });
  status.classList.remove('settings-error');
  status.textContent = 'Testing read-only access to ShipStation carriers and shipments…';
  const payload = Object.fromEntries(new FormData(connectionForm));
  try {
    const response = await api(save ? '/api/settings/shipstation' : '/api/settings/shipstation/test', {method: save ? 'PUT' : 'POST', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    if (save) {
      defaultsCatalog = null;
      applyWorkspaceSettings(response);
      availableProviders = await api('/api/providers');
      connectionForm.reset();
      defaultsCatalog = null;
      document.querySelector('#status').textContent = 'Workspace ready. ShipStation connection verified.';
      status.textContent = 'Connection saved and applied. No restart required.';
    } else {
      status.textContent = response.message;
      status.classList.toggle('settings-error', !response.connected);
      if (!payload.api_key && !payload.api_secret) {
        workspaceSettings.connection.last_test = response;
        document.querySelector('#connection-summary').textContent = response.message;
      }
    }
  } catch (error) { status.textContent = error.message; status.classList.add('settings-error'); }
  finally { buttons.forEach(button => { button.disabled = false; }); }
}
document.querySelector('#test-connection').onclick = () => connectShipStation(false);
connectionForm.addEventListener('submit', event => { event.preventDefault(); connectShipStation(true); });
