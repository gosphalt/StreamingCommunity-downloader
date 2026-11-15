# Diario di bordo

Registro sintetico di miglioramenti, test e decisioni. Una voce per sessione, dalla più recente.

## 2026-11-15 (test di `test_search_sources.py`)

- **Causa:** `app/core/animeunity.py` legge `r.is_redirect` e `r.headers` (commit `ae8c494`), ma il fake `_ArchiveResponse` del test non li aveva. Il codice di produzione è corretto.
- **Modifica:** `tests/test_search_sources.py`: il fake ha `headers` e `is_redirect` come `requests.Response`. Nuovo test `test_a_redirected_archive_post_is_sent_again_to_the_new_location`, che copre il secondo POST a mano dopo un 302.
- **Test:** `test_search_sources.py`: 47 passati. Suite completa: 1149 passati, 0 falliti.
- **Aperto:** modifiche non committate. Il join annullato non è ancora provato su un download reale.

## 2026-11-15 (riavvio bloccato dagli stream SSE)

- **Causa:** `/api/progress/stream` e `/api/progress/{job_id}` sono cicli infiniti (keepalive ogni 25-30 s). Una scheda aperta tiene una connessione, e uvicorn, all'arresto, aspetta che si chiuda. Il riavvio è durato 90 s, poi systemd ha forzato con SIGKILL.
- **Modifica:** `main.py`: `uvicorn.run(..., timeout_graceful_shutdown=5)`. Dopo 5 s uvicorn chiude le connessioni residue e poi esegue lo shutdown del lifespan.
- **Test:** server di prova con stream infinito. Senza limite lo stop ha impiegato 39 s (aspettava il client); con limite 5,4 s. Sul servizio reale: il primo riavvio (con il vecchio `main.py` ancora in memoria) ha impiegato 90 s, il secondo meno di 1 s con shutdown completo.
- **Aperto:** modifica non committata. Lo stream è stato verificato solo su un server di prova, non su un browser collegato al panel. I 16 test rossi di `tests/test_search_sources.py` sono stati corretti (vedi sotto).

## 2026-11-15 (annullamento del join e rilascio della chiamata)

- **Modifica:** `app/core/m3u8.py`, `M3U8_Segments.join()`: FFmpeg ora parte con `run_async` e viene atteso a passi di 0,5 s. Un annullamento lo uccide subito (`DownloadCancelledError`), prima `run()` non si poteva interrompere. stderr è letto da un thread, altrimenti il buffer si riempie e blocca FFmpeg.
- **Modifica:** `app/jobs.py`: a job finito `_finish()` azzera `job.call` (gli argomenti, lista di episodi per una stagione intera). `_persist()` esce subito se non c'è più nulla da salvare. Un job in errore conserva la chiamata per il retry.
- **Test:** nuovi `tests/test_join_cancel.py` (3) e `tests/test_job_call_released.py` (2). Insieme a `tests/test_output_container.py`: 39 passati. Suite completa: 1132 passati, 16 falliti, tutti in `tests/test_search_sources.py`. Causa: `app/core/animeunity.py:216` chiama `r.is_redirect` su `_ArchiveResponse`, che non lo ha. Il guasto esiste già su `main` (verificato in un worktree temporaneo: 16 falliti, 30 passati su `test_search_sources.py`), dal commit `ae8c494` che ha cambiato la chiamata dell'archivio in POST. Da correggere a parte, il test fake non ha `is_redirect`.
- **Commit:** `6269c6f` su `fix/cancel-join-release-call` (le modifiche sono state committate in una sessione precedente). Merge in `main` fatto in locale, non pushato.
- **Aperto:** il join annullato non è ancora provato su un download reale. Il test `test_search_sources.py` era rosso su `main`: risolto nella voce sotto.

## 2026-11-15 (download e JOIN_COMMON)

- **Modifica:** `app/core/container.py`, `JOIN_COMMON`: audio da `-c:a aac -b:a 192k -af aresample` a `-c:a copy`. Video già in copia. Usato da ogni unione (video e tracce audio).
- **Test:** aggiunto `test_the_join_copies_the_audio_never_reencodes_it` in `tests/test_output_container.py`. `tests/test_output_container.py`: 35 passati.
- **Verifica:** remux di prova con `-c:a copy` da `_combined.ts` reale in MP4: riuscito, audio AAC, durata corretta. Prova MKV non completata (file sorgente già rimosso).
- **Commit:** `5e8cbc5` su branch `fix/copy-audio-on-join`. Non ancora pushato, né PR aperta. Esclusi dal commit `app/core/m3u8.py`, `app/jobs.py`, `tests/test_job_call_released.py` (modifiche preesistenti non mie).
- **Riavvio pannello:** `sudo systemctl restart scpanel.service`, eseguito alle 16:13 con la nuova versione.
- **Download LOTR (1° tentativo):** annullato dall'utente alle 16:10 con il vecchio codice. Output parziale rimosso dal codice di pulizia.
- **Download LOTR (2° tentativo, job `923dc9a4`):** completato alle 16:33 con il nuovo codice. Video H.264, audio AAC `ita` ed `eng` copiati (bitrate uguale alla sorgente, 130 kbps), sottotitoli `.en.vtt` accanto al file. Durata 10700 s. Il remux finale ha impiegato circa 2 minuti.
- **Decodifica audio:** `ffmpeg -f null` su entrambe le tracce, exit 0 e nessun errore. Video non decodificato fotogramma per fotogramma.
- **Concorrenza:** `max_concurrent_downloads` resta a 1. Il copy riduce il tempo fuori dal download a circa il 15%, mentre `max_segment_workers` (16) è un tetto condiviso: il parallelo guadagnerebbe poco e aumenterebbe il rischio di 429. Da rivalutare solo misurando con due download.
- **Monitor:** fermati. Il secondo monitor (`monitor_lotr3.sh`) ha scritto `DONE`.

## 2026-11-15

**Obiettivo:** creare o aggiornare `CLAUDE.md` con `/init`.

- Verificato che `CLAUDE.md` esiste già: non sovrascritto, solo proposte di miglioramento.
- Letti `.gitlab-ci.yml`, `.github/workflows/docker-publish.yml`, `Dockerfile`, `app/core/CLAUDE.md`.
- Proposte pendenti per `CLAUDE.md`:
  - comando per un singolo test (`pytest tests/x.py::test_nome -q`);
  - CI su Python 3.11 con `pytest -q`;
  - nessun lint/formatter configurato;
  - riferimento a `app/core/CLAUDE.md`;
  - serve un virtualenv con `requirements-dev.txt`.
- Test: non eseguiti (comando rifiutato). Stato sconosciuto.
- Modifiche al codice: nessuna.
