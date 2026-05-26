# Midas Docker Deployment

## Build and Run Locally

```bash
cp .env.example .env
# Fill required values in .env

docker build -t midas:local .
docker run --rm \
  -p 8000:8000 \
  --env-file .env \
  -e CLIENT_SECRETS_FILE=/app/client_secret.json \
  -e KEYFRAMES_LOCAL_DIR=/app/storage/keyframes \
  -v "$(pwd)/client_secret.json:/app/client_secret.json:ro" \
  -v midas_storage:/app/storage \
  midas:local
```

Open `http://localhost:8000`.

## Use the GHCR Image

On another machine, create a folder containing:

```text
docker-compose.yml
.env
client_secret.json
```

Then run:

```bash
docker compose up -d
```

To update:

```bash
docker compose pull
docker compose up -d
```

To view logs:

```bash
docker compose logs -f midas
```

## Notes

- `.env` is passed to the running container at runtime. It is not baked into the image.
- `client_secret.json` is mounted at runtime and excluded from the image by `.dockerignore`.
- The app runs on port `8000`.
- Keyframe files are persisted in the `midas_storage` Docker volume.
