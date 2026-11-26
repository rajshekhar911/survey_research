/* Participant survey: consent -> product-choice screens -> thank you.
   One tap per screen: choosing a listing saves it and moves on.
   Progress is saved on the server, so a refresh resumes at the same screen. */
'use strict';
(() => {
  const { esc } = Listing;
  const app = document.getElementById('app');
  const bar = document.getElementById('progress-fill');
  const LS_KEY = 'b2a_survey_token';
  const params = new URLSearchParams(location.search);

  let settings = {};
  let S = null;
  let token = null;
  let page = null;

  const lsGet = () => { try { return localStorage.getItem(LS_KEY); } catch (e) { return null; } };
  const lsSet = (v) => { try { localStorage.setItem(LS_KEY, v); } catch (e) { /* private mode */ } };

  async function api(path, body) {
    let res;
    try {
      res = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
    } catch (e) {
      throw new Error('Could not reach the server. Please check your internet connection and try again.');
    }
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      const err = new Error(data.error || `Something went wrong (${res.status}). Please try again.`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function logEvent(type, detail) {
    if (token) api('/api/event', { token, page, type, detail }).catch(() => {});
  }

  function render(html) {
    app.innerHTML = html;
    window.scrollTo(0, 0);
    const h = app.querySelector('h1');
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
  }

  function showError(msg) {
    const box = app.querySelector('.error');
    if (box) { box.textContent = msg; box.hidden = false; box.scrollIntoView({ block: 'center' }); }
    else alert(msg);
  }

  const nTasks = () => S.design.tasks.length;
  const setProgress = (done) => { bar.style.width = `${Math.round((done / nTasks()) * 100)}%`; };

  // ------------------------------------------------------------- pages
  function consentPage() {
    page = 'consent';
    const s = settings;
    render(`
      <h1>${esc(s.study_title)}</h1>
      <div class="info">
        <p>You will see <b>${esc(s.n_tasks)} short screens</b>, each with three listings of an
          everyday product. <b>Tap the one you would buy.</b> That's all. It takes about
          ${esc(s.estimated_minutes)} minutes.</p>
        <p class="muted">Taking part is voluntary and anonymous; you can stop at any time by closing
          this page. Answers are used only for academic research.
          ${esc(s.researcher_name)}, ${esc(s.institution)} · ${esc(s.contact_email)} ·
          Ethics approval ${esc(s.ethics_ref)}</p>
      </div>
      <label class="consent"><input type="checkbox" id="agree">
        <span>I am 18 or older and I agree to take part.</span></label>
      <div class="error" role="alert" hidden></div>
      <div class="nav"><button type="button" class="primary" id="start">Start</button></div>`);
    document.getElementById('start').addEventListener('click', async (ev) => {
      if (!document.getElementById('agree').checked) return showError('Please tick the box to agree before starting.');
      ev.target.disabled = true;
      try {
        adopt(await api('/api/start', {
          consent: true, pid: params.get('pid') || '', src: params.get('src') || '',
          viewport: `${window.innerWidth}x${window.innerHeight}`,
        }));
      } catch (e) {
        ev.target.disabled = false;
        showError(e.message);
      }
    });
  }

  function taskPage(i) {
    page = `task_${i}`;
    document.body.classList.add('task');
    setProgress(i);
    const task = S.design.tasks[i];
    const c = S.categories[task.category];
    const shown = Date.now();
    let locked = false;
    render(`
      <div class="task-head">
        <div class="muted">Screen ${i + 1} of ${nTasks()}</div>
        <h1>You need ${esc(c.need)}. Which one would you buy?</h1>
      </div>
      ${Listing.taskHTML(task, S.categories)}
      <div class="error" role="alert" hidden></div>`);

    app.querySelectorAll('button.choose').forEach((b) => b.addEventListener('click', async () => {
      if (locked) return;
      locked = true;
      const pos = Number(b.dataset.pos);
      app.querySelectorAll('.listing').forEach((el) => {
        const on = Number(el.dataset.pos) === pos;
        el.classList.toggle('selected', on);
        el.querySelector('button.choose').textContent = on ? '✓ Selected' : 'Choose this';
      });
      const pause = new Promise((r) => setTimeout(r, 300));  // brief visual confirmation
      try {
        await api('/api/choice', { token, task: i, chosen_pos: pos, ms: Date.now() - shown });
        await pause;
        if (i + 1 < nTasks()) taskPage(i + 1); else finish();
      } catch (e) {
        if (e.status === 409) return boot();
        locked = false;
        showError(e.message);
      }
    }));
    app.querySelectorAll('button.verify').forEach((b) => b.addEventListener('click', () => {
      const alt = task.alts[Number(b.dataset.pos)];
      openRegistry(alt, c, { task: i, pos: alt.pos, brand: alt.brand });
    }));
  }

  function openRegistry(alt, c, detail) {
    const opened = Date.now();
    logEvent('verify_open', detail);
    const wrap = document.createElement('div');
    wrap.className = 'modal-wrap';
    wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="Certificate lookup">
      <div class="lookup"><span class="spinner" aria-hidden="true"></span> Looking up ${esc(alt.cert_id)}…</div>
      <div class="result" hidden>${Listing.registryHTML(alt, c)}</div>
      <button type="button" class="primary close">Close</button></div>`;
    document.body.appendChild(wrap);
    const close = () => {
      logEvent('verify_close', { ...detail, ms: Date.now() - opened });
      wrap.remove();
      document.removeEventListener('keydown', onKey);
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
    wrap.querySelector('.close').addEventListener('click', close);
    wrap.querySelector('.close').focus();
    setTimeout(() => {
      if (!wrap.isConnected) return;
      wrap.querySelector('.lookup').hidden = true;
      wrap.querySelector('.result').hidden = false;
    }, 700);
  }

  async function finish() {
    page = 'finish';
    document.body.classList.remove('task');
    render('<p class="lead">Saving…</p>');
    try {
      S = { ...S, ...(await api('/api/complete', { token })) };
      donePage();
    } catch (e) {
      render(`<h1>Almost done</h1><p class="error">${esc(e.message)}</p>
        <div class="nav"><button class="primary" id="retry">Try again</button></div>`);
      document.getElementById('retry').addEventListener('click', () => (e.status === 409 ? boot() : finish()));
    }
  }

  function donePage() {
    page = 'done';
    document.body.classList.remove('task');
    bar.style.width = '100%';
    const fict = [];
    S.design.tasks.forEach((t) => t.alts.forEach((a) => {
      if (a.fictitious && !fict.includes(a.brand)) fict.push(a.brand);
    }));
    const redirect = S.redirect;
    render(`
      <h1>Thank you!</h1>
      <div class="code-box">Your completion code<br><b>${esc(S.completion_code)}</b></div>
      <div class="info"><p class="muted">Please note: some brands were made up for this survey
        (${esc(fict.join(', '))}), and the prices, ratings, descriptions and certificates
        were hypothetical. Nothing here endorses any brand.</p></div>
      ${redirect ? `<div class="nav"><a class="primary button" href="${esc(redirect)}" rel="noreferrer">Continue</a></div>` : ''}`);
    if (redirect) setTimeout(() => { location.href = redirect; }, 5000);
  }

  // ------------------------------------------------------------ routing
  function adopt(st) {
    S = st;
    token = st.token;
    lsSet(token);
    if (st.status === 'completed') return donePage();
    const m = /^task_(\d+)$/.exec(st.current_page || '');
    if (m && Number(m[1]) < nTasks()) return taskPage(Number(m[1]));
    return finish();
  }

  async function boot() {
    try {
      settings = await (await fetch('/api/settings')).json();
      document.title = settings.study_title || document.title;
    } catch (e) { /* defaults */ }
    const saved = token || lsGet();
    if (saved) {
      try { return adopt(await api('/api/resume', { token: saved })); } catch (e) { /* start fresh */ }
    }
    consentPage();
  }

  document.addEventListener('visibilitychange', () => {
    if (page && page.startsWith('task_')) {
      logEvent(document.hidden ? 'visibility_hidden' : 'visibility_visible', {});
    }
  });

  boot();
})();
