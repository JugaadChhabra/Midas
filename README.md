# Midas

AI-assisted YouTube metadata auditor with human-in-the-loop review.

## Quickstart

### 1. Install
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

For the local shorts cutter (heavy ML deps, local runs only — not needed in Docker):
`pip install -r requirements-ml.txt`. Also requires `ffmpeg` and `node` on PATH.

### 2. Configure env
```bash
cp .env.example .env
# fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, OPENROUTER_API_KEY
```
Your Google OAuth `client_secret_*.json` is already in the repo root and referenced by `CLIENT_SECRETS_FILE`.

### 3. Push schema to Supabase
Project is already linked via `supabase link`. Push the migration:
```bash
supabase db push
```

### 4. Run
```bash
export $(grep -v '^#' .env | xargs)   # so OAUTHLIB_INSECURE_TRANSPORT=1 takes effect
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:3000 — wait, the redirect URI in your OAuth client is `http://localhost:8000/auth/callback`, so use **http://localhost:8000**. Click *Connect channel*, sign in with the Google account that owns the YouTube channel, and you'll be redirected back with the channel saved to Supabase.

## Notes
- `prompt="consent"` is on so Google always returns a refresh token. Remove for prod.
- `DRY_RUN=true` — write-back will log payloads instead of pushing to YouTube. Flip when ready.
- Refresh tokens are stored in plaintext for now. Encrypt before any non-personal channel.
