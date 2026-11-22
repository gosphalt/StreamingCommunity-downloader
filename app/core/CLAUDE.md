# vixcloud quirks

The video host is never hardcoded. It moved from `vixcloud.co` to `vixcloud.cc` and every download
broke, so `_shared.embed_host()` reads it off the embed URL the source itself hands over (SC iframe,
AnimeUnity `/embed-url/`), `_parse_content()` stores it as `json_win_video["host"]`, and playlist,
`enc.key` and referers are built from that. The playlist key allowlist (`_KEY_HOSTS`) matches the
second-level label only, any TLD.

Both moving hosts have a manual escape hatch in Settings › Sorgente › "Altri host"
(`GET/PUT /api/domain/hosts`, stored in `data.json` as `animeunity_domain` and `video_host`).
AnimeUnity resolves saved → `ANIMEUNITY_HOST` env → `config.ANIMEUNITY_DEFAULT_HOST`, read per call
through `animeunity.host()`. `video_host` is empty normally; when set, `_shared.apply_video_host()`
moves the embed URL onto it *before* anything is fetched, so embed page, playlist, key and referers
all follow. Every value goes through `hosts.normalize_host()` (bare hostname, no IP/port/path) and is
verified against the service it claims to be — AnimeUnity's page, a 16-byte `/storage/enc.key` —
before it is stored.

TV episode M3U8 URLs sometimes return 403; appending `?b=1` (or `&b=1`) resolves it. Handled in
`_fetch_text_with_b1_fallback` and `_collect_audio_tracks`.

## Domain, metadata and stream fallback

- **A domain found automatically is proposed, never adopted.** The page it comes from is edited by
  people we do not control, and the domain decides where every search, image fetch and download
  referer goes. `domain_recovery.is_plausible()` is the guard, and its load-bearing rule is that a
  candidate must be a **second-level domain**: checking only the first label would accept
  `streamingcommunity.attacker.tld`, where the part that decides where the traffic lands is the
  attacker's. The name pattern is a module constant with an env override and **must not become a
  settings field** — a text box that relaxes an SSRF guard is a loaded gun. `verify()` is
  deliberately stricter than `PUT /api/domain`, which accepts an empty version string: an admin
  typing a host in is making a decision, a web page is not. `domain_auto_apply` opts out of all of
  this and is off by default.
- **Title metadata has one provider and needs no credential.** It comes from the title page's own
  props — the payload already fetched to find `tmdb_id` — so it costs no request of its own. Two
  other providers were tried and removed after being measured, and the measurements are the reason:
  the site's `/api/titles/preview` endpoint answers 419 (Laravel CSRF) to every request the panel
  can make and never once worked, while TMDB turned out not to be an upgrade at all — the site
  copies its synopses from TMDB, so the text was usually identical, and the round trip *lost* a
  trailer on one title, a logo on another and 1100 characters of plot on a third. Do not re-add a
  provider without measuring it against the props on real titles first.
- **`metadata.cached_tmdb_id()` never does I/O.** A stream fallback would read it at download time,
  and a download that is about to succeed must not pay a round trip to discover a fallback it will
  not use.
- **When stream resolution has nothing to fall back to, the primary error must survive.**
  `_FALLBACK_PROVIDERS` is empty: a second road through vixsrc was built and removed, because that
  site is now a client-rendered app whose HTML carries no playlist, token or `.m3u8` at all — the
  data would have to come from reverse-engineered internal calls that break silently on any of
  their deploys. `resolve_stream()` is the seam a replacement plugs into, and the resolution
  context (`tmdb_id`, media type, season, episode) is already threaded from every caller.
  A user told "no alternative source" when the real failure was Cloudflare has been sent to debug
  the wrong thing, so the original exception is re-raised unchanged. AnimeUnity is excluded from
  all of it on purpose: no TMDB id, different embed host. `fetch_key_from_playlist()` exists so a
  new provider does not have to solve the key again — it is read from the playlist with an
  allowlisted host, never assumed.

## Container

- **The container is one setting read in one place, and nothing is ever re-encoded.**
  `container.configured()` is the only source; `paths.*_path()` take `container=` the way they take
  `templates=`, and everything downstream infers the container from the extension of the file it is
  handed rather than from a second lookup — which is what makes the temp audio tracks (genuinely
  `.mp4`) mux correctly while the destination is Matroska. Three consequences worth knowing.
  `movflags` is mov/mp4-private: handed to the matroska muxer FFmpeg refuses the whole command, at
  the end of the download, after every byte is fetched. The remux now reads and writes the *same*
  extension, so it stages a dot-prefixed sibling in the library folder and `os.replace()`s it —
  dot-prefixed because a Jellyfin scan running meanwhile would otherwise index the half-written
  file as a second copy, and a sibling rather than something under `tmp/` because `os.replace`
  cannot cross a filesystem. And `resolver.candidate_paths()` probes one extension per known
  container, configured first: two axes, one stat each, which is what
  `tests/test_naming_library_check.py` pins at exactly two. A finished download deletes the same
  stem in the *other* container, because Jellyfin reads `Film.mkv` and `Film.mp4` in one folder as
  two versions of one film — the exact sibling only, and only once the new file is complete. Video and audio are always stream-copied
  — the source is H.264 + AAC, native to both — so the only conversion is WebVTT to `mov_text`, and
  only when subtitles are embedded into MP4. A transcoding option does not belong here: it would
  turn a four-minute download into an hours-long CPU job under a stall watchdog built for neither.
