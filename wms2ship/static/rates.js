let rateRevision = 0;
let rateFingerprint = null;
let selectedRate = null;
let rateExpires = 0;
let rateExpiryTimer;
let applyComparedRate = null;
let rateBusy = false;
const rateMoney = value => (value / 100).toLocaleString('en-US', {style: 'currency', currency: 'USD'});
function rateFormFingerprint() {
  return JSON.stringify({order: currentOrder?.id, config: configurationPayload(), scope: 'standard'});
}
function ratePurchaseAllowed() {
  if (formValue('shipping.provider') === 'fake') return !rateBusy;
  return !!selectedRate && Date.now() < rateExpires && rateFingerprint === rateFormFingerprint() && !rateBusy;
}
function updateRatePurchaseText() {
  const button = document.querySelector('#create-label');
  if (formValue('shipping.provider') === 'shipstation') {
    button.textContent = selectedRate ? `Buy shipping label · est. ${rateMoney(selectedRate.total_minor)}` : 'Buy shipping label';
  }
}
function resetRateComparison() {
  ++rateRevision;
  clearTimeout(rateExpiryTimer);
  rateFingerprint = null; selectedRate = null; rateExpires = 0; rateBusy = false;
  applyComparedRate = null;
  document.querySelector('#rates-status').textContent = 'Rates load automatically when carrier choices are ready.';
  document.querySelector('#rates-warnings').replaceChildren();
  document.querySelector('#quote-results').hidden = true;
  document.querySelector('#quote-results').replaceChildren();
  document.querySelector('#rate-selection').textContent = '';
  document.querySelector('#compare-rates').disabled = false;
}
function invalidateRates(reason) {
  ++rateRevision;
  clearTimeout(rateExpiryTimer);
  rateFingerprint = null; selectedRate = null; rateExpires = 0; rateBusy = false;
  document.querySelector('#quote-results').hidden = true;
  document.querySelector('#rate-selection').textContent = '';
  document.querySelector('#rates-warnings').replaceChildren();
  document.querySelector('#rates-status').textContent = reason;
  document.querySelector('#compare-rates').disabled = false;
  updateCreateLabel();
}
function checkRateChanges() {
  if (rateFingerprint && rateFingerprint !== rateFormFingerprint()) invalidateRates('Shipping details changed. Compare rates again.');
}
async function compareRates() {
  if (!currentOrder || labelRequestInFlight || rateBusy) return;
  if (!catalogLoaded) {
    document.querySelector('#rates-status').textContent = 'Carrier choices are unavailable. Check the connection error above, then reopen this order.';
    return;
  }
  invalidateRates('Comparing prices…');
  const revision = rateRevision;
  const orderId = currentOrder.id;
  rateFingerprint = rateFormFingerprint();
  rateBusy = true;
  document.querySelector('#compare-rates').disabled = true;
  updateCreateLabel();
  try {
    const result = await api(`/api/orders/${orderId}/rates`, {method: 'POST',
      headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'},
      body: JSON.stringify({...configurationPayload(), scope: 'standard'})});
    if (revision !== rateRevision || rateFingerprint !== rateFormFingerprint()) return;
    rateExpires = result.rates.length ? Date.now() + result.valid_for_seconds * 1000 : 0;
    document.querySelector('#rate-note').textContent = result.note;
    const warningBox = document.querySelector('#rates-warnings');
    for (const warning of result.warnings) message(warningBox, warning);
    document.querySelector('#rates-status').textContent = result.rates.length
      ? `${result.rates.length} estimates · ${result.partial ? 'Some carriers unavailable · ' : ''}checked ${new Date(result.quoted_at).toLocaleTimeString()} · refresh after 5 minutes${result.mode === 'test' ? ' · test-label creation mode' : ''}`
      : 'No quotes available. Review the details below and try again.';
    const body = document.querySelector('#quote-results');
    body.replaceChildren();
    document.querySelector('#quote-results').hidden = !result.rates.length;
    const groups = new Map();
    result.rates.forEach((rate, index) => {
      if (!groups.has(rate.carrier_code)) {
        const brand = carrierBrand(rate.carrier_code);
        const group = message(body, '', 'article');
        group.className = `carrier-quotes carrier-${brand.tone}`;
        const header = message(group, '', 'header');
        header.className = 'carrier-quote-header';
        const identity = message(header, '', 'div');
        identity.className = 'carrier-identity';
        if (brand.logo) {
          const logo = document.createElement('img');
          logo.src = `/static/carriers/${brand.logo}`;
          logo.alt = `${brand.name} logo`;
          logo.className = 'carrier-logo';
          logo.addEventListener('error', () => { logo.hidden = true; });
          identity.append(logo);
        }
        message(identity, brand.name || rate.carrier_name, 'strong');
        message(header, rate.carrier_name, 'span');
        const cards = message(group, '', 'div');
        cards.className = 'carrier-quote-grid';
        groups.set(rate.carrier_code, cards);
      }
      const choose = message(groups.get(rate.carrier_code), '', 'button');
      choose.className = 'quote-card';
      choose.type = 'button';
      choose.dataset.rateIndex = index;
      choose.setAttribute('aria-pressed', 'false');
      choose.title = `${rate.package_name} · Shipping ${rateMoney(rate.shipment_minor)} + other ${rateMoney(rate.other_minor)} USD`;
      choose.setAttribute('aria-label', `Select ${rate.carrier_name} ${rate.service_name} ${rateMoney(rate.total_minor)}`);
      if (rate.total_minor === result.rates[0].total_minor) {
        message(choose, 'Lowest returned price', 'span').className = 'quote-best';
      }
      message(choose, rate.service_name, 'strong').className = 'quote-service';
      message(choose, rate.package_name, 'span').className = 'quote-package';
      message(choose, rateMoney(rate.total_minor), 'strong').className = 'quote-price';
      message(choose, `USD · Shipping ${rateMoney(rate.shipment_minor)} + other ${rateMoney(rate.other_minor)}`, 'span').className = 'quote-breakdown';
      message(choose, 'Select service', 'span').className = 'quote-choice';
      choose.addEventListener('click', () => {
        if (Date.now() >= rateExpires || rateFingerprint !== rateFormFingerprint()) {
          invalidateRates('Quotes expired or details changed. Compare rates again.'); return;
        }
        try {
          if (!applyComparedRate) throw new Error('Carrier choices are unavailable. Reopen this order.');
          applyComparedRate(rate);
          selectedRate = rate;
          rateFingerprint = rateFormFingerprint();
          body.querySelectorAll('.quote-card').forEach(card => {
            const selected = Number(card.dataset.rateIndex) === index;
            card.classList.toggle('selected-rate', selected);
            card.setAttribute('aria-pressed', String(selected));
            card.querySelector('.quote-choice').textContent = selected ? '✓ Selected' : 'Select service';
          });
          document.querySelector('#rate-selection').textContent = `Selected: ${rate.carrier_name} / ${rate.service_name} · estimate ${rateMoney(rate.total_minor)} USD. Review the shipment below before purchasing.`;
          scheduleReadiness();
          document.querySelector('#final-review').scrollIntoView({behavior: 'smooth', block: 'start'});
        } catch (error) { invalidateRates(error.message); }
      });
    });
    if (result.rates.length) {
      document.querySelector('#basic-step').open = false;
      document.querySelector('.rates-card').scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    rateExpiryTimer = setTimeout(() => invalidateRates('Quotes expired. Compare rates again before buying.'), result.valid_for_seconds * 1000);
  } catch (error) {
    if (revision !== rateRevision) return;
    rateFingerprint = null;
    document.querySelector('#rates-status').textContent = error.message;
  } finally {
    if (revision === rateRevision) {
      rateBusy = false; document.querySelector('#compare-rates').disabled = !!rateFingerprint && Date.now() < rateExpires; updateCreateLabel();
    }
  }
}
document.querySelector('#compare-rates').addEventListener('click', compareRates);

function renderShipmentReview() {
  const target = document.querySelector('#shipment-review');
  if (!target || !currentOrder) return;
  target.replaceChildren();
  const add = (title, value) => {
    const item = message(target, '', 'div');
    message(item, title, 'strong');
    message(item, value || 'Not selected', 'span');
  };
  const recipient = currentOrder.recipient;
  add('Ship to', [recipient.name, recipient.address1, recipient.address2, recipient.city, recipient.state, recipient.postal, recipient.country].filter(Boolean).join(' · '));
  add('Ship from', ['name', 'address1', 'city', 'state', 'postal', 'country'].map(key => formValue(`origin.${key}`)).filter(Boolean).join(' · '));
  add('Ship date', formValue('shipping.ship_date'));
  document.querySelector('#basic-summary').textContent = `${formValue('origin.city') || 'Shipper needed'} → ${recipient.city || recipient.country} · ${formValue('package.weight_g') || '?'} oz · ${formValue('shipping.ship_date') || 'Choose date'}`;
  add('Package', packageUnits.map(([key, label]) => `${formValue(`package.${key}`) || '?'} ${label}`).join(' · '));
  add('Selected quote', selectedRate ? `${selectedRate.carrier_name} · ${selectedRate.service_name} · ${selectedRate.package_name}` : formValue('shipping.provider') === 'fake' ? 'Simulation · choose service options below' : 'Get quotes and select a service in step 2');
  add('Estimated price', selectedRate ? rateMoney(selectedRate.total_minor) + ' USD · actual charge may differ' : '—');
}

function carrierBrand(code) {
  const normalized = code.toLowerCase();
  if (normalized === 'stamps_com' || normalized.startsWith('usps')) return {name: 'USPS', tone: 'usps', logo: 'usps.svg'};
  if (normalized.startsWith('ups')) return {name: 'UPS', tone: 'ups', logo: 'ups.svg'};
  if (normalized.startsWith('fedex')) return {name: 'FedEx', tone: 'fedex', logo: 'fedex.png'};
  if (normalized.startsWith('globalpost')) return {name: 'GlobalPost', tone: 'globalpost', logo: 'globalpost.svg'};
  return {name: '', tone: 'other', logo: null};
}
