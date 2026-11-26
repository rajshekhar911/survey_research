/* Renders product listings. Shared by the survey (app.js) and the admin
   stimulus viewer (stimulus.js) so agent screenshots match what people saw. */
'use strict';
const Listing = (() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inr = (n) => '₹' + Number(n).toLocaleString('en-IN');

  function stars(r) {
    const pct = Math.max(0, Math.min(100, (r / 5) * 100)).toFixed(0);
    return `<span class="stars" role="img" aria-label="${esc(r)} out of 5 stars">` +
      `<span class="stars-fill" style="width:${pct}%"></span></span>`;
  }

  function warrantyText(cat, years) {
    const label = cat.warranty_label || 'Warranty';
    if (!years) return `${label}: none`;
    return `${label}: ${years} year${years > 1 ? 's' : ''}`;
  }

  function claimBlock(alt, cat, opts) {
    if (alt.claim === 'none') return '';
    if (alt.claim === 'unverifiable') {
      return `<div class="claim"><span class="tick">✔</span> ${esc(alt.claim_text)}</div>`;
    }
    const idLabel = cat.cert.type === 'BIS' ? 'Licence No.' : 'Report No.';
    const btn = opts.verify === false ? '' :
      ` <button type="button" class="verify" data-pos="${alt.pos}">Verify</button>`;
    return `<div class="claim"><span class="tick">✔</span> ${esc(alt.claim_text)}` +
      `<div class="certid">${idLabel} ${esc(alt.cert_id)}${btn}</div></div>`;
  }

  function card(alt, cat, opts = {}) {
    const affect = alt.affect ? `
      <div class="affect-banner" aria-hidden="true">
        <div class="scene">${esc(cat.affect.scene)}</div>
        <div class="tagline">“${esc(alt.tagline)}”</div>
        <div class="tv">📺 As seen on TV</div>
      </div>` : '';
    const about = alt.backstory
      ? `<div class="about"><b>About ${esc(alt.brand)}:</b> ${esc(alt.backstory)}</div>` : '';
    const spec = cat.spec.map(([k, v]) =>
      `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');
    const button = opts.buttons === false ? '' :
      `<button type="button" class="choose" data-pos="${alt.pos}">Choose this</button>`;
    return `
    <article class="listing${alt.affect ? ' has-affect' : ''}" data-pos="${alt.pos}">
      <div class="optlabel">Option ${String.fromCharCode(65 + alt.pos)}</div>
      ${affect}
      <div class="pimg" aria-hidden="true">${esc(cat.icon)}</div>
      <div class="lbody">
        <div class="brand">${esc(alt.brand)}</div>
        <h3 class="ptitle">${esc(alt.brand)} ${esc(cat.title)}</h3>
        <div class="rating">${stars(alt.rating)} <b>${esc(alt.rating.toFixed(1))}</b>
          <span class="muted">(${Number(alt.reviews).toLocaleString('en-IN')} ratings)</span></div>
        <div class="price">${inr(alt.price)}</div>
        <div class="warranty">${esc(warrantyText(cat, alt.warranty_years))}</div>
        ${claimBlock(alt, cat, opts)}
        ${about}
        <table class="spec"><caption>Specifications</caption><tbody>${spec}</tbody></table>
        ${button}
      </div>
    </article>`;
  }

  function taskHTML(task, cats, opts = {}) {
    const cat = cats[task.category];
    return `<div class="listings">${task.alts.map((a) => card(a, cat, opts)).join('')}</div>`;
  }

  function registryHTML(alt, cat) {
    if (cat.cert.type === 'BIS') {
      return `<h2>BIS licence lookup</h2>
        <p class="muted">Bureau of Indian Standards: product certification register</p>
        <table class="spec"><tbody>
          <tr><th>Licence No.</th><td>${esc(alt.cert_id)}</td></tr>
          <tr><th>Status</th><td><b class="ok">Operative</b></td></tr>
          <tr><th>Brand</th><td>${esc(alt.brand)}</td></tr>
          <tr><th>Product</th><td>${esc(cat.cert.product)}</td></tr>
          <tr><th>Standard</th><td>${esc(cat.cert.standard)}</td></tr>
          <tr><th>Valid until</th><td>31-03-2028</td></tr>
        </tbody></table>`;
    }
    return `<h2>Test report lookup</h2>
      <p class="muted">NABL-accredited laboratory: test report register</p>
      <table class="spec"><tbody>
        <tr><th>Report No.</th><td>${esc(alt.cert_id)}</td></tr>
        <tr><th>Product</th><td>${esc(alt.brand)} ${esc(cat.title)}</td></tr>
        <tr><th>Test</th><td>${esc(cat.cert.product)}</td></tr>
        <tr><th>Result</th><td><b class="ok">Pass</b></td></tr>
        <tr><th>Issued</th><td>2026</td></tr>
      </tbody></table>`;
  }

  return { esc, inr, card, taskHTML, registryHTML };
})();
