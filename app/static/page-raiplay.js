// RaiPlay tab: search the public catalogue, open a programme, download a film
// or an episode. The server builds every RaiPlay URL from the paths it hands out;
// the browser only sends those paths back. Loaded after page-search.js, which
// owns the source switcher and the action map.

let _rpAbort = null;
let _rpResultsHtml = '';   // the last search grid, so "back" needs no request
let _rpProgram = null;     // the programme open in the panel, for season "back"

function _showRaiplayMode(on) {
  if (on) _setStartPageVisible(false);
  const browse = document.getElementById('browse-bar');
  if (browse && on) browse.style.display = 'none';
  const filters = document.getElementById('search-filters');
  if (filters && on) filters.innerHTML = '';
}

function _rpPut(html) {
  document.getElementById('search-results').innerHTML = html;
}

function _rpSpinner(text) {
  return `<div class="col-12 text-center text-secondary py-4">` +
    `<span class="spinner-border spinner-border-sm me-2"></span>${escapeHtml(text)}</div>`;
}

function _rpHead(backAction, backData, title) {
  return `<div class="col-12 d-flex align-items-center gap-2 mb-2">` +
    `<button class="btn btn-outline-secondary btn-sm" data-action="${backAction}" ${backData}>` +
    `<i class="ti ti-arrow-left me-1"></i>Indietro</button>` +
    `<h3 class="h5 m-0">${escapeHtml(title)}</h3></div>`;
}

async function doRaiplaySearch(q) {
  if (_rpAbort) _rpAbort.abort();
  _rpAbort = new AbortController();
  _rpPut(_rpSpinner('Cerco su RaiPlay...'));
  try {
    const items = await api.get('/api/raiplay/search', {q}, {signal: _rpAbort.signal});
    if (!items.length) {
      _rpPut('<div class="col-12 text-center text-secondary py-4">Nessun risultato.</div>');
      return;
    }
    _rpResultsHtml = items.map(it => `
      <div class="col-6 col-sm-4 col-md-3 col-lg-2">
        <div class="result-card">
          <div class="card-meta">
            <div class="card-title-text" title="${escapeHtml(it.name)}">${escapeHtml(it.name)}</div>
            <div class="text-secondary small">${it.year ? escapeHtml(it.year) + ' · ' : ''}${it.media_type === 'film' ? 'Film' : 'Serie'}</div>
            <button class="btn btn-primary btn-sm w-100 mt-2" data-action="rp:open" data-path="${escapeHtml(it.path)}">
              <i class="ti ti-list me-1"></i>Apri
            </button>
          </div>
        </div>
      </div>`).join('');
    _rpPut(_rpResultsHtml);
  } catch (e) {
    if (e.name === 'AbortError') return;
    _rpPut('');
    showToast(e.message || 'Ricerca RaiPlay fallita', 'danger');
  }
}

async function rpOpen(path) {
  _rpPut(_rpSpinner('Apro il programma...'));
  try {
    const p = await api.get('/api/raiplay/program', {path});
    _rpProgram = p;
    const title = p.year ? `${p.name} (${p.year})` : p.name;
    const head = _rpHead('rp:back', '', title);
    const desc = p.description
      ? `<div class="col-12 text-secondary small mb-3">${escapeHtml(p.description)}</div>` : '';
    if (p.media_type === 'film') {
      const btn = p.video
        ? `<button class="btn btn-primary" data-action="rp:download" data-kind="film" ` +
          `data-video="${escapeHtml(p.video)}" data-title="${escapeHtml(p.name)}" ` +
          `data-year="${escapeHtml(p.year)}"><i class="ti ti-download me-1"></i>Scarica film</button>`
        : '<span class="text-secondary">Nessun video disponibile.</span>';
      _rpPut(head + desc + `<div class="col-12">${btn}</div>`);
      return;
    }
    const seasons = p.seasons.map(s =>
      `<button class="btn btn-outline-primary btn-sm me-2 mb-2" data-action="rp:season" ` +
      `data-path="${escapeHtml(s.path)}" data-name="${escapeHtml(s.name)}">` +
      `${escapeHtml(s.name || 'Stagione')}</button>`).join('');
    _rpPut(head + desc + `<div class="col-12">${seasons || '<span class="text-secondary">Nessuna stagione.</span>'}</div>`);
  } catch (e) {
    _rpPut('');
    showToast(e.message || 'Impossibile aprire il programma RaiPlay', 'danger');
  }
}

async function rpSeason(path, name) {
  if (!_rpProgram) return rpBack();
  const p = _rpProgram;
  _rpPut(_rpSpinner('Carico gli episodi...'));
  try {
    const eps = await api.get('/api/raiplay/season', {path});
    const head = _rpHead('rp:open', `data-path="${escapeHtml(p.path)}"`, `${p.name} · ${name}`);
    const rows = eps.map(e => {
      // An episode RaiPlay lists without a number (a dated programme) has no
      // place in a series folder, so it is shown and not offered for download.
      const numbered = /^\d{1,4}$/.test(e.season) && /^\d{1,4}$/.test(e.episode);
      const action = numbered
        ? `<button class="btn btn-primary btn-sm" data-action="rp:download" data-kind="episode" ` +
          `data-video="${escapeHtml(e.video)}" data-title="${escapeHtml(e.title)}" ` +
          `data-series="${escapeHtml(p.name)}" data-year="${escapeHtml(p.year)}" ` +
          `data-season="${escapeHtml(e.season)}" data-episode="${escapeHtml(e.episode)}">` +
          `<i class="ti ti-download me-1"></i>Scarica</button>`
        : '<span class="text-secondary small">senza numero: non scaricabile</span>';
      const label = (e.episode ? `Ep. ${e.episode} · ` : '') + (e.title || 'Episodio');
      return `<div class="col-12 d-flex align-items-center justify-content-between gap-2 border-bottom py-2">` +
        `<div class="text-truncate">${escapeHtml(label)}` +
        `${e.duration ? ` <span class="text-secondary small">${escapeHtml(e.duration)}</span>` : ''}</div>` +
        `${action}</div>`;
    }).join('');
    _rpPut(head + `<div class="col-12">${rows || '<span class="text-secondary">Nessun episodio.</span>'}</div>`);
  } catch (e) {
    _rpPut('');
    showToast(e.message || 'Impossibile caricare la stagione', 'danger');
  }
}

async function rpDownload(d, el) {
  el.disabled = true;
  const body = {kind: d.kind, video: d.video, title: d.title};
  if (d.year) body.year = d.year;
  if (d.kind === 'episode') Object.assign(body, {series: d.series, season: d.season, episode: d.episode});
  try {
    await api.post('/api/download/raiplay', body);
    el.innerHTML = '<i class="ti ti-check me-1"></i>In coda';
    showToast('Download avviato', 'success');
  } catch (e) {
    el.disabled = false;
    showToast(e.message || 'Impossibile avviare il download', 'danger');
  }
}

function rpBack() {
  _rpPut(_rpResultsHtml);
}
