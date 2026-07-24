# NAS Shorts Cutting — Deploy Checklist

How to get Midas cutting shorts from the office NAS. The office machine runs the
**prebuilt image** (`ghcr.io/jugaadchhabra/midas:latest`, auto-built by CI on every
push to `main`) — it does **not** need the codebase, only `docker-compose.yml` and
the files below.

---

## 1. Files the office machine needs (next to `docker-compose.yml`)

| File | Purpose |
|------|---------|
| `docker-compose.yml` | pulls the image, wires ports/volumes/env |
| `.env` | **all** the config — the usual gap (see §2) |
| `client_secret.json` | Google OAuth client (mounted read-only) |
| `storage/`, `shorts_cache/`, `logs/` | created on first run if absent |

## 2. `.env` — the block that must be present

The dashboard/UI and the cutter both fail silently if these are missing or wrong.

```dotenv
# --- NAS (shorts cutter source/sink) ---
NAS_MODE=smb
NAS_SERVER=10.1.1.3
NAS_SHARE=<share name>
NAS_USERNAME=<user>
NAS_PASSWORD=<pass>
NAS_DOMAIN=
NAS_PORT=445
NAS_AUTH_PROTOCOL=ntlm    # standalone NAS (raw IP, local user) can't do Kerberos; leave "ntlm". Only an AD-joined share needs "negotiate".
NAS_SOURCE_ROOT_PATH=Animations/SHORTS CUTTER/RHYMES        # MUST directly contain the language subfolders
NAS_DESTINATION_ROOT_PATH=Animations/SHORTS CUTTER/COMPLETED

# --- rest of the stack ---
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
# + OpenRouter / YouTube / etc. keys as usual

# optional: cut more in parallel (default 2, bounded by host CPU/GPU)
SHORTS_MAX_CONCURRENT_JOBS=2
```

> `NAS_SOURCE_ROOT_PATH` is the folder whose **direct children** are the language
> folders (`PUNJABI/`, `BHOJPURI/`, `MARATHI/`, `HINDI/`, …). Off by one level →
> everything reads empty even when the NAS is reachable.

## 3. Deploy

```bash
# 1. Make sure the latest GitHub Actions "docker-publish" run is GREEN
#    (so :latest has the code you expect).
# 2. On the office machine, on the office LAN:
docker compose pull
docker compose up -d
```

## 4. Verify (this is the real test — not the dropdown)

```bash
curl localhost:8000/shorts/languages
```

- Returns `[{"language":"PUNJABI","uncut":N}, ...]` → **working.** The channel-page
  folder dropdown will now show each channel's saved folder (hard-refresh the page).
- Returns `[]` or errors → **NAS not reachable / visible.** It's not a UI bug. Check,
  in order: (1) on the office LAN? (2) `NAS_SERVER`/`NAS_SHARE`/creds correct?
  (3) `NAS_SOURCE_ROOT_PATH` points at the folder that *contains* the language dirs.

Same check from a shell:
```bash
docker compose exec midas python -m scripts.cut_language --list
```

## 5. Cutting

Once §4 passes, cutting is automatic for every channel that has **both** a
`nas_folder` set **and** `autopilot_shorts_enabled = true`. Autopilot enqueues every
uncut file per channel (paced by the dispatcher); each job: fetch from NAS → cut →
save clips to `…/COMPLETED/<LANG>/` → **move the source out** so it's never re-cut.

Kick a full sweep immediately (instead of waiting for the ~120 s round-robin):
```bash
docker compose exec midas python -m scripts.cut_language PUNJABI
docker compose exec midas python -m scripts.cut_language BHOJPURI
docker compose exec midas python -m scripts.cut_language MARATHI
```

## 6. Current channel config (as of 2026-07-23)

| Channel | `nas_folder` | `autopilot_shorts_enabled` |
|---------|--------------|-----------------------------|
| …Punjabi  | `PUNJABI`  | ✅ on |
| …Bhojpuri | `BHOJPURI` | ✅ on |
| …Marathi  | `MARATHI`  | ✅ on |
| …Rhymes / Baalgeet | `HINDI` | off (enable when ready; needs a real HINDI folder on the NAS) |

Change these via the channel-page Shorts card, the channel API, or directly in the
`channels` table (`nas_folder`, `autopilot_shorts_enabled`).

## Troubleshooting

- **Dropdown shows "none" for every channel** → `/shorts/languages` is returning
  `[]`. The saved folder values ARE in the DB; the UI just can't build the option
  list because it can't see the NAS. Fix NAS reachability (§4), not the UI.
- **A channel with a folder set still shows "none"** → that folder doesn't exist in
  the NAS listing (e.g. `HINDI` set but no `HINDI/` folder). Create it or repoint.
- **Configured but no jobs appear** → the running container is on a stale image
  (pre-NAS code) or can't reach the NAS. `docker compose pull` + re-check §4.
- **`SMBAuthenticationError: ... Unable to negotiate common mechanism` / "No username
  or password was specified"** even though the creds are right → the SMB client tried
  Kerberos (the default `negotiate` mode) against a standalone NAS that has no KDC.
  Ensure `NAS_AUTH_PROTOCOL=ntlm` (now the default). Confirm inside the container:
  `docker compose exec midas python -c "import smbclient; smbclient.register_session('<server>', username='<u>', password='<p>', auth_protocol='ntlm'); print(smbclient.listdir(r'\\<server>\<share>'))"`
- **`local` mode for dev/off-network:** set `NAS_MODE=local` and point
  `NAS_SOURCE_ROOT_PATH` at a local folder containing `PUNJABI/`, `BHOJPURI/`, … with
  a few `.mp4`s. No SMB needed.
