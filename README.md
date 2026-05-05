# File Upload Server

A small FastAPI service for private file sharing and clipboard syncing.

It includes:

- Login-protected web workspace
- Private clipboard history per user
- Chunked, resumable, parallel web uploads
- Expiring uploaded files
- Stable token-based upload API
- Docker-friendly deployment

## Quick Start

```bash
cp .env.example .env
cp config.yaml.example config.yaml
./hash-password.sh --yaml example-user
docker compose up -d --build
```

Edit `config.yaml` before starting the service:

- Set a strong `app.session_secret`
- Replace the example user and `password_hash`
- Adjust retention and clipboard limits if needed

The app runs on:

```text
http://localhost:8091
```

## Runtime Files

The repository keeps only safe example configuration.

Do not commit:

- `.env`
- `config.yaml`
- `data/`

For production, keep real runtime files outside the repository and point Docker Compose at this source directory.

## API

The token API is a shared upload channel. It is separate from the web workspace and does not isolate files by web user.

All API uploads are saved into the same server upload path:

```text
/app/data
```

Use this header when `UPLOAD_TOKEN` is configured:

```text
X-Upload-Token: <your-token>
```

If `UPLOAD_TOKEN` is empty, token API auth is disabled.

## License

MIT. See `LICENSE`.
