'use strict';
(() => {
  const { esc } = Listing;
  const app = document.getElementById('app');
  const q = new URLSearchParams(location.search);
  const el = document.getElementById('task-data');
  if (!el) { app.textContent = 'No task data.'; return; }
  const { task, categories } = JSON.parse(el.textContent);
  const cat = categories[task.category];
  const buttons = q.get('buttons') !== '0';
  app.innerHTML = `
    <div class="task-head">
      <h1>You need ${esc(cat.need)}. Which one would you buy?</h1>
    </div>
    ${Listing.taskHTML(task, categories, { buttons })}`;
  app.querySelectorAll('button.verify').forEach((b) => b.addEventListener('click', () => {
    const alt = task.alts[Number(b.dataset.pos)];
    const w = document.createElement('div');
    w.className = 'modal-wrap';
    w.innerHTML = `<div class="modal">${Listing.registryHTML(alt, cat)}
      <button type="button" class="primary close">Close</button></div>`;
    w.querySelector('.close').addEventListener('click', () => w.remove());
    document.body.appendChild(w);
  }));
})();
