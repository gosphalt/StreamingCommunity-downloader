/* StreamingCommunity Web Panel — page-favorites.js */
//
// Titles starred from the search. The heart on a card calls in here; the list
// is its own page. Favorites are few, so the whole set is held client-side and
// the cards are painted from it instead of asking the server per page.

let _favorites = [];
let _favLoaded = false;

const favKind = item => (item.type === 'anime' ? 'anime' : (item.type === 'movie' ? 'movie' : 'tv'));
const _favKey = (source, kind, id) => `${source}/${kind}/${id}`;
const _favRowKey = f => _favKey(f.source, f.kind, f.external_id);

function _favSource(item) {
  return item.type === 'anime' ? 'animeunity' : 'streamingcommunity';
}

async function loadFavorites() {
  const grid = document.getElementById('favorites-grid');
  try {
    _favorites = (await api.get('/api/favorites')).favorites || [];
    _favLoaded = true;
  } catch (e) {
    if (grid) grid.innerHTML = `<p class="text-muted">${escapeHtml(errText(e, 'Impossibile caricare i preferiti.'))}</p>`;
    return;
  }
  renderFavorites();
  paintFavorites();
}

// Loaded once at boot for the hearts on the search cards.
async function ensureFavorites() {
  if (_favLoaded || !(can('REQUEST') || can('DOWNLOAD'))) return;
  try {
    _favorites = (await api.get('/api/favorites')).favorites || [];
    _favLoaded = true;
    paintFavorites();
  } catch (e) { /* hearts stay empty */ }
}

function paintFavorites() {
  const keys = new Set(_favorites.map(_favRowKey));
  document.querySelectorAll('.fav-btn[data-idx]').forEach(btn => {
    const item = _searchResults[Number(btn.dataset.idx)];
    const on = !!item && keys.has(_favKey(_favSource(item), favKind(item), item.id));
    btn.classList.toggle('on', on);
    btn.innerHTML = `<i class="ti ti-heart${on ? '-filled' : ''}"></i>`;
    btn.title = on ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti';
  });
}

async function toggleFavorite(idx) {
  const item = _searchResults[idx];
  if (!item) return;
  const source = _favSource(item), kind = favKind(item), id = String(item.id);
  const existing = _favorites.find(f => _favRowKey(f) === _favKey(source, kind, id));
  try {
    if (existing) {
      await api.del(`/api/favorites/${source}/${kind}/${encodeURIComponent(id)}`);
      _favorites = _favorites.filter(f => f !== existing);
    } else {
      const body = {
        source, kind, external_id: id, title: item.name, slug: item.slug || null,
        year: itemYear(item), poster: item.poster || null,
        anime_type: item.type === 'anime' ? (item.media_type || null) : null,
      };
      await api.post('/api/favorites', body);
      _favorites = [{ ...body, created_at: new Date().toISOString() }, ..._favorites];
    }
    paintFavorites();
  } catch (e) {
    showToast(errText(e, 'Impossibile aggiornare i preferiti.'), 'error');
  }
}

function renderFavorites() {
  const grid = document.getElementById('favorites-grid');
  if (!grid) return;
  if (!_favorites.length) {
    grid.innerHTML = `<div class="empty-panel">
      <i class="ti ti-heart-off"></i>
      <p>Nessun preferito.</p>
      <p class="text-muted" style="font-size:12px;margin-top:6px">
        Premi il cuore su un titolo della ricerca per ritrovarlo qui.
      </p>
    </div>`;
    return;
  }
  grid.innerHTML = _favorites.map((f, i) => {
    const poster = f.poster
      ? (f.poster.startsWith('http') ? f.poster : `/api/image/${f.poster}`) : '';
    const kind = kindBadge({ type: f.kind, media_type: f.anime_type });
    return `<div class="col-6 col-sm-4 col-md-3 col-lg-2">
      <div class="result-card" data-action="fav:open" data-i="${i}">
        <div class="poster-wrap">
          ${poster ? `<img src="${poster}" alt="" loading="lazy" onerror="posterError(this)">` : ''}
          <div class="poster-noimg" style="${poster ? 'display:none' : ''}">&#127916;</div>
          <button class="fav-btn on" data-action="fav:remove" data-i="${i}" title="Rimuovi dai preferiti">
            <i class="ti ti-heart-filled"></i></button>
        </div>
        <div class="card-meta">
          <div class="card-title-text" title="${escapeHtml(f.title)}">${escapeHtml(f.title)}</div>
          <div class="card-badges">
            <span class="badge ${kind.cls}">${escapeHtml(kind.label)}</span>
            ${f.year ? `<span style="font-size:10px;color:var(--text-muted)">${escapeHtml(f.year)}</span>` : ''}
          </div>
        </div>
      </div>
    </div>`;
  }).join('');
}

function openFavorite(i) {
  const f = _favorites[i];
  if (!f) return;
  const seed = {
    name: f.title, type: f.kind, id: f.external_id, slug: f.slug || '',
    poster: f.poster, media_type: f.anime_type, release_date: f.year ? `${f.year}-01-01` : null,
  };
  // The same seed the search hands over, so the title page paints at once.
  _tpSeed = seed;
  location.hash = titleHash(seed);
}

async function removeFavorite(i) {
  const f = _favorites[i];
  if (!f) return;
  try {
    await api.del(`/api/favorites/${f.source}/${f.kind}/${encodeURIComponent(f.external_id)}`);
    _favorites.splice(i, 1);
    renderFavorites();
  } catch (e) {
    showToast(errText(e, 'Impossibile rimuovere il preferito.'), 'error');
  }
}

registerActions({
  'fav:toggle': d => toggleFavorite(Number(d.idx)),
  'fav:open':   d => openFavorite(Number(d.i)),
  'fav:remove': d => removeFavorite(Number(d.i)),
});

registerPageHash('favorites', { read: () => ({}), apply: () => {} });
