// Libri tab: public-domain books from Internet Archive, with filters. The server
// picks the file from the item; the browser sends only the item's identifier.
// Loaded after page-search.js, which owns the source switcher and the action map.

let _bkAbort = null;

const _BK_LANGUAGES = [['', 'Tutte le lingue'], ['ita', 'Italiano'], ['eng', 'Inglese'],
  ['fra', 'Francese'], ['deu', 'Tedesco'], ['spa', 'Spagnolo'], ['lat', 'Latino']];

function _showBooksMode(on) {
  if (on) _setStartPageVisible(false);
  const browse = document.getElementById('browse-bar');
  if (browse && on) browse.style.display = 'none';
  const filters = document.getElementById('search-filters');
  if (filters) filters.innerHTML = on ? _bkFiltersHtml() : '';
}

function _bkFiltersHtml() {
  const langs = _BK_LANGUAGES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  return `<div class="col-12 d-flex flex-wrap align-items-end gap-2 mb-2">` +
    `<div><label class="form-label small mb-1">Lingua</label>` +
    `<select id="bk-lang" class="form-select form-select-sm">${langs}</select></div>` +
    `<div><label class="form-label small mb-1">Anno da</label>` +
    `<input id="bk-from" type="number" min="1" max="2100" class="form-control form-control-sm" style="width:6.5rem"></div>` +
    `<div><label class="form-label small mb-1">a</label>` +
    `<input id="bk-to" type="number" min="1" max="2100" class="form-control form-control-sm" style="width:6.5rem"></div>` +
    `<div><label class="form-label small mb-1">Autore</label>` +
    `<input id="bk-creator" type="text" maxlength="120" class="form-control form-control-sm" style="width:12rem"></div>` +
    `<div><button class="btn btn-primary btn-sm" data-action="books:search">` +
    `<i class="ti ti-search me-1"></i>Cerca</button></div></div>`;
}

function _bkPut(html) {
  document.getElementById('search-results').innerHTML = html;
}

async function doBooksSearch(q) {
  if (_bkAbort) _bkAbort.abort();
  _bkAbort = new AbortController();
  const params = {
    q: q || '',
    language: document.getElementById('bk-lang')?.value || '',
    year_from: document.getElementById('bk-from')?.value || '',
    year_to: document.getElementById('bk-to')?.value || '',
    creator: document.getElementById('bk-creator')?.value || '',
  };
  _bkPut('<div class="col-12 text-center text-secondary py-4">Cerco su Internet Archive...</div>');
  try {
    const items = await api.get('/api/books/search', params, {signal: _bkAbort.signal});
    if (!items.length) {
      _bkPut('<div class="col-12 text-center text-secondary py-4">Nessun libro trovato.</div>');
      return;
    }
    _bkPut(items.map(it => `
      <div class="col-6 col-sm-4 col-md-3 col-lg-2">
        <div class="result-card"><div class="card-meta">
          <div class="card-title-text" title="${escapeHtml(it.title)}">${escapeHtml(it.title)}</div>
          <div class="text-secondary small">${escapeHtml(it.creator || 'Autore sconosciuto')}</div>
          <div class="text-secondary small">${it.year ? escapeHtml(it.year) + ' · ' : ''}${escapeHtml(it.language || '')}</div>
          <button class="btn btn-primary btn-sm w-100 mt-2" data-action="books:download"
            data-identifier="${escapeHtml(it.identifier)}" data-title="${escapeHtml(it.title)}"
            data-creator="${escapeHtml(it.creator || '')}" data-year="${escapeHtml(it.year || '')}">
            <i class="ti ti-download me-1"></i>Scarica</button>
        </div></div>
      </div>`).join(''));
  } catch (e) {
    if (e.name === 'AbortError') return;
    _bkPut('');
    showToast(e.message || 'Ricerca libri fallita', 'danger');
  }
}

async function bkDownload(d, el) {
  el.disabled = true;
  try {
    await api.post('/api/books/download', {
      identifier: d.identifier, title: d.title, creator: d.creator || '', year: d.year || '',
    });
    el.innerHTML = '<i class="ti ti-check me-1"></i>In coda';
    showToast('Download avviato', 'success');
  } catch (e) {
    el.disabled = false;
    showToast(e.message || 'Impossibile avviare il download', 'danger');
  }
}
