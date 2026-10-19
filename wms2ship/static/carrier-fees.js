// Read-only billing report. Download uses the successfully displayed range.
const feeForm = document.querySelector('#fee-filters');
const feeStatus = document.querySelector('#fee-status');
const feeDownload = document.querySelector('#download-fees');
const feeMore = document.querySelector('#fee-more');
let feeQuery = new URLSearchParams();
let feeOffset = 0;
let feeRevision = 0;
let feeBusy = false;
const feeTodayParts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago', year: 'numeric', month: '2-digit', day: '2-digit'
}).formatToParts(new Date()).map(part => [part.type, part.value]));
feeForm.elements.namedItem('start').value = `${feeTodayParts.year}-${feeTodayParts.month}-01`;
feeForm.elements.namedItem('end').value = `${feeTodayParts.year}-${feeTodayParts.month}-${feeTodayParts.day}`;

function feeMoney(minor, currency) {
  return minor == null ? 'Missing fee' : `${(minor / 100).toFixed(2)} ${currency}`;
}

async function loadFees(reset = true) {
  if (!reset && feeBusy) return;
  const revision = ++feeRevision;
  feeBusy = true;
  feeMore.disabled = true;
  document.querySelector('#fee-refresh').disabled = true;
  if (reset) {
    feeDownload.hidden = true;
    feeMore.hidden = true;
    for (const selector of ['#fee-summary', '#fee-details tbody']) document.querySelector(selector).replaceChildren();
    document.querySelector('#fee-warning').hidden = true;
  }
  feeStatus.textContent = 'Reading ShipStation account shipments…';
  feeStatus.classList.remove('fee-error');
  try {
    const query = reset ? new URLSearchParams(new FormData(feeForm)) : new URLSearchParams(feeQuery);
    for (const [key, value] of [...query]) if (!value) query.delete(key);
    query.set('offset', reset ? 0 : feeOffset);
    const data = await api(`/api/carrier-fees?${query}`);
    if (revision !== feeRevision) return;
    if (reset) {
      feeOffset = 0;
      feeQuery = new URLSearchParams(data.filters);
      feeForm.elements.namedItem('start').value = data.filters.start;
      feeForm.elements.namedItem('end').value = data.filters.end;
      feeDownload.href = `/api/carrier-fees/report.xlsx?${feeQuery}`;
      feeDownload.hidden = false;
      const cards = document.querySelector('#fee-summary');
      const totals = data.summary.totals.map(total => [
        `Total shipping fees${data.summary.missing_fees ? " (incomplete)" : ""} (${total.currency})`, feeMoney(total.charge_minor, total.currency)
      ]);
      for (const [label, value] of [['Orders', data.summary.orders], ['Shipments', data.summary.labels], ...totals]) {
        const card = message(cards, '', 'div');
        message(card, value, 'strong');
        message(card, label, 'span');
      }
      const warnings = [];
      if (!data.total) warnings.push('No shipments returned by ShipStation for this period.');
      if (data.summary.missing_fees) warnings.push(`${data.summary.missing_fees} label(s) have a missing fee. Totals are incomplete; review before billing.`);
      if (data.summary.voided_excluded) warnings.push(`${data.summary.voided_excluded} voided shipment(s) excluded from the total.`);
      const warning = document.querySelector('#fee-warning');
      warning.textContent = warnings.join(' ');
      warning.hidden = !warnings.length;

    }
    const details = document.querySelector('#fee-details tbody');
    for (const row of data.rows) {
      const tr = message(details, '', 'tr');
      for (const value of [row.wms_order_no, row.tracking_number || '—', row.recipient || '—']) message(tr, value, 'td');
      const carrier = message(tr, '', 'td');
      message(carrier, row.carrier_name || row.carrier || '—', 'strong');
      message(carrier, row.service_name || row.service || 'Not recorded', 'small');
      message(tr, feeMoney(row.charge_minor, row.currency), 'td');
    }
    feeOffset += data.rows.length;
    feeMore.hidden = feeOffset >= data.total;
    if (!data.total) message(message(details, '', 'tr'), 'No shipments returned by ShipStation for this period.', 'td').colSpan = 5;
    feeStatus.textContent = `${data.filters.start} through ${data.filters.end} · ShipStation ship date · ${feeOffset} of ${data.total} shipment(s) shown. Excel includes every row in this period.`;
  } catch (error) {
    if (revision === feeRevision) {
      feeStatus.textContent = error.message;
      feeStatus.classList.add('fee-error');
    }
  } finally {
    if (revision === feeRevision) {
      feeBusy = false;
      feeMore.disabled = false;
      document.querySelector('#fee-refresh').disabled = false;
    }
  }
}

feeForm.addEventListener('submit', event => { event.preventDefault(); loadFees(true); });
feeForm.addEventListener('change', () => loadFees(true));
feeMore.addEventListener('click', () => loadFees(false));
document.querySelector('#tab-fees').addEventListener('click', () => loadFees(true));
if (location.hash === '#fees') loadFees(true);
