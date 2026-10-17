// Read-only browser folder access works with native, Docker, and HTTPS deployments.
(() => {
  const get = id => document.getElementById(id);
  const supported = !!window.showDirectoryPicker && window.isSecureContext;
  let permitted = false;
  let folder = null;
  let entries = [];
  let scanning = false;
  let importing = false;
  let generation = 0;
  const fingerprints = new Map();
  const selected = new Set();
  const MAX_BYTES = 10 * 1024 * 1024;
  const keyOf = entry => `${entry.name}:${entry.sha256}`;
  const selectable = entry => ['new', 'needs_review'].includes(entry.status);
  const labels = { new: 'New — never imported', imported: 'Imported', needs_review: 'Import attempted — needs review', copying: 'Still copying — waiting', large: 'Too large (10 MB maximum)', unreadable: 'Cannot read file' };

  function storedFolder(operation, value) {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('wms-folder-inbox', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('handles');
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const tx = db.transaction('handles', operation === 'get' ? 'readonly' : 'readwrite');
        const store = tx.objectStore('handles');
        const action = operation === 'get' ? store.get('folder') : operation === 'put' ? store.put(value, 'folder') : store.delete('folder');
        let result;
        action.onsuccess = () => { result = action.result; };
        tx.oncomplete = () => { db.close(); resolve(result); };
        tx.onerror = () => { db.close(); reject(tx.error); };
        tx.onabort = () => { db.close(); reject(tx.error || new Error('Folder storage unavailable.')); };
      };
    });
  }

  function controls() {
    const ready = !!folder && permitted && !scanning && !importing;
    get('choose-folder').disabled = !supported || scanning || importing;
    get('refresh-folder').disabled = !ready;
    get('stop-folder').hidden = !folder;
    get('stop-folder').disabled = scanning || importing;
    get('select-new-files').disabled = !ready || (!selected.size && !entries.some(e => e.status === 'new'));
    get('select-new-files').textContent = selected.size ? 'Clear selection' : 'Select new files';
    get('import-folder-files').textContent = selected.size ? `Import selected (${selected.size})` : 'Import selected';
    get('import-folder-files').disabled = !ready || !entries.some(e => selectable(e) && selected.has(keyOf(e)));
  }

  function render() {
    const body = get('folder-table').tBodies[0];
    body.replaceChildren();
    const visible = entries.filter(e => get('show-imported-files').checked || e.status !== 'imported');
    if (!visible.length) {
      const td = message(message(body, '', 'tr'), folder ? 'No unimported XLSX files in this folder.' : 'No folder selected.', 'td');
      td.colSpan = 5;
    }
    for (const entry of visible) {
      const tr = message(body, '', 'tr');
      const cell = message(tr, '', 'td');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.disabled = !selectable(entry) || importing || !permitted;
      checkbox.checked = selected.has(keyOf(entry));
      checkbox.setAttribute('aria-label', `Import ${entry.name}`);
      checkbox.onchange = () => {
        if (checkbox.checked) selected.add(keyOf(entry)); else selected.delete(keyOf(entry));
        controls();
      };
      cell.append(checkbox);
      message(tr, entry.name, 'td');
      message(tr, entry.modified ? new Date(entry.modified).toLocaleString() : '—', 'td');
      message(tr, entry.size == null ? '—' : `${Math.ceil(entry.size / 1024)} KB`, 'td');
      const state = message(tr, labels[entry.status], 'td');
      if (entry.batch_id && entry.status === 'needs_review') {
        const button = message(state, 'View issues', 'button');
        button.type = 'button';
        button.onclick = async () => {
          try { await showImport(await api(`/api/imports/${entry.batch_id}`)); }
          catch (error) { get('folder-import-status').textContent = error.message; }
        };
      }
    }
    controls();
  }

  async function digest(file) {
    return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())), b => b.toString(16).padStart(2, '0')).join('');
  }

  async function scan() {
    if (!folder || scanning || importing) return;
    const current = folder;
    const revision = generation;
    scanning = true;
    controls();
    try {
      permitted = await current.queryPermission({ mode: 'read' }) === 'granted';
      if (!permitted) {
        get('reconnect-folder').hidden = false;
        get('folder-status').textContent = `Reconnect “${current.name}” to resume folder checks.`;
        render();
        return;
      }
      get('reconnect-folder').hidden = true;
      const found = [];
      const present = new Set();
      for await (const handle of current.values()) {
        if (handle.kind !== 'file' || !/\.xlsx$/i.test(handle.name) || handle.name.startsWith('~$') || handle.name.startsWith('.')) continue;
        const entry = { name: handle.name, handle };
        present.add(handle.name);
        try {
          const file = await handle.getFile();
          entry.size = file.size;
          entry.modified = file.lastModified;
          if (file.size > MAX_BYTES) entry.status = 'large';
          else if (!file.size || Date.now() - file.lastModified < 2000) entry.status = 'copying';
          else {
            const signature = `${file.size}:${file.lastModified}`;
            const cached = fingerprints.get(handle.name);
            entry.sha256 = cached?.signature === signature ? cached.sha256 : await digest(file);
            fingerprints.set(handle.name, { signature, sha256: entry.sha256 });
          }
        } catch { entry.status = 'unreadable'; }
        found.push(entry);
      }
      const hashes = [...new Set(found.filter(e => e.sha256).map(e => e.sha256))];
      const known = new Map();
      for (let i = 0; i < hashes.length; i += 200) {
        const result = await api('/api/imports/check', { method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }, body: JSON.stringify({ hashes: hashes.slice(i, i + 200) }) });
        result.files.forEach(file => known.set(file.sha256, file));
      }
      if (generation !== revision) return;
      for (const entry of found) if (entry.sha256) Object.assign(entry, known.get(entry.sha256));
      entries = found.sort((a, b) => (b.modified || 0) - (a.modified || 0) || a.name.localeCompare(b.name));
      for (const name of fingerprints.keys()) if (!present.has(name)) fingerprints.delete(name);
      const available = new Set(entries.filter(selectable).map(keyOf));
      for (const key of selected) if (!available.has(key)) selected.delete(key);
      const count = status => entries.filter(e => e.status === status).length;
      get('folder-status').textContent = `${current.name} · ${count('new')} new · ${count('needs_review')} need review · ${count('imported')} imported · Checked ${new Date().toLocaleTimeString()}`;
      render();
    } catch (error) {
      get('folder-status').textContent = `Folder check failed: ${error.message}. Choose the folder again if access was removed.`;
    } finally { scanning = false; controls(); }
  }

  async function showImport(detail) {
    const target = get('import-result');
    message(target, `${detail.filename}: ${detail.summary.created} new orders, ${detail.summary.duplicates} existing, ${detail.summary.invalid} invalid.`, 'h3');
    for (const row of detail.rows) if (row.issues.length) message(target, `${row.sheet}, row ${row.row}: ${row.issues.join(' ')}`);
  }

  get('choose-folder').onclick = async () => {
    try {
      generation++;
      const chosen = await window.showDirectoryPicker({ id: 'wms-import-inbox', mode: 'read' });
      folder = chosen;
      generation++;
      entries = [];
      fingerprints.clear();
      selected.clear();
      try { await storedFolder('put', folder); }
      catch { get('folder-import-status').textContent = 'Folder is connected for this session; your browser could not remember it.'; }
      await scan();
    } catch (error) { if (error.name !== 'AbortError') get('folder-status').textContent = `Cannot open folder: ${error.message}`; }
  };
  get('reconnect-folder').onclick = async () => {
    try {
      if (await folder.requestPermission({ mode: 'read' }) === 'granted') await scan();
      else get('folder-status').textContent = 'Folder access was not granted. Choose another folder or use the file picker.';
    } catch (error) { get('folder-status').textContent = error.message; }
  };
  get('refresh-folder').onclick = scan;
  get('stop-folder').onclick = async () => {
    folder = null;
    permitted = false;
    generation++;
    entries = [];
    selected.clear();
    fingerprints.clear();
    get('reconnect-folder').hidden = true;
    get('folder-status').textContent = 'Folder disconnected. Your files and import history are unchanged.';
    render();
    try { await storedFolder('delete'); } catch { /* The current session is still disconnected. */ }
  };
  get('show-imported-files').onchange = render;
  get('select-new-files').onclick = () => {
    if (selected.size) selected.clear();
    else entries.filter(e => e.status === 'new').forEach(e => selected.add(keyOf(e)));
    render();
  };
  get('import-folder-files').onclick = async () => {
    if (importing || scanning) return;
    const queue = entries.filter(e => selectable(e) && selected.has(keyOf(e)));
    importing = true;
    get('import-result').replaceChildren();
    render();
    let imported = 0;
    const errors = [];
    const seen = new Set();
    try {
      for (const entry of queue) {
        if (seen.has(entry.sha256)) { selected.delete(keyOf(entry)); continue; }
        seen.add(entry.sha256);
        get('folder-import-status').textContent = `Importing ${entry.name}…`;
        try {
          const file = await entry.handle.getFile();
          if (file.size > MAX_BYTES || file.size !== entry.size || file.lastModified !== entry.modified || await digest(file) !== entry.sha256) throw new Error('File changed since the last check. Refresh and select it again.');
          const batch = await api(`/api/imports?filename=${encodeURIComponent(entry.name)}`, { method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/octet-stream' }, body: file });
          imported++;
          selected.delete(keyOf(entry));
          await showImport(await api(`/api/imports/${batch.id}`));
        } catch (error) { errors.push(`${entry.name}: ${error.message}`); }
      }
      await loadOrders();
      get('folder-import-status').textContent = `${imported} file(s) processed.${errors.length ? ` ${errors.join(' ')}` : ' Review any row issues above.'}`;
    } catch (error) { get('folder-import-status').textContent = error.message; }
    finally { importing = false; await scan(); render(); }
  };

  document.addEventListener('wms-import-complete', scan);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) scan(); });
  setInterval(() => { if (!document.hidden) scan(); }, 15000);
  render();
  if (!supported) {
    get('choose-folder').disabled = true;
    get('folder-status').textContent = 'Folder monitoring requires Chrome or Edge on localhost or HTTPS. The file picker above is still available.';
  } else {
    storedFolder('get').then(async saved => {
      if (!saved || folder || generation) return;
      folder = saved;
      await scan();
    }).catch(() => { /* A folder can still be chosen without persistence. */ });
  }
})();
