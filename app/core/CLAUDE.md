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
