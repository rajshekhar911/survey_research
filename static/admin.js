'use strict';
(() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (id) => document.getElementById(id);

  const stat = (n, l) => `<div class="stat"><div class="n">${esc(n ?? '–')}</div><div class="l">${esc(l)}</div></div>`;
  const table = (head, rows) => `<thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>` +
    `<tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ''}>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody>`;

  async function load() {
    let res;
    try { res = await fetch('/admin/api/stats', { cache: 'no-store' }); } catch (e) { res = null; }
    if (!res || !res.ok) {
      $('cards').textContent = 'Could not load stats. Open /admin without a username or password in the address bar and log in when asked.';
      return;
    }
    const s = await res.json();
    const c = s.counts || {};
    $('cards').innerHTML = [
      stat(s.total, 'started (consented)'),
      stat(c.started || 0, 'in progress / dropped'),
      stat(s.completed, 'completed'),
      stat(s.flags.quality_pass, 'quality pass'),
      stat(s.median_minutes, 'median minutes'),
    ].join('');
    $('flags').innerHTML = table(['Flag', 'Count'], Object.entries(s.flags).map(([k, v]) => [k, v]));
    $('perday').innerHTML = table(['Day (UTC)', 'Completes'], s.per_day.map((d) => [d.day, d.n]));
    const labels = { claim: 'Claim', affect: 'Affect layer', brand_type: 'Brand type', price_mult: 'Price × reference', rating: 'Rating' };
    $('shares').innerHTML = Object.entries(labels).map(([k, l]) => {
      const rows = (s.choice_shares[k] || []).map((x) => [x.level, x.shown, x.chosen, x.share.toFixed(3)]);
      return `<h3>${esc(l)}</h3><table class="data">${table(['Level', 'Shown', 'Chosen', 'Share'], rows)}</table>`;
    }).join('');
    $('updated').textContent = `updated ${new Date().toLocaleTimeString()}`;
  }

  load();
  setInterval(load, 60000);
})();
