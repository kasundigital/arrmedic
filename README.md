<p align="center">
  <img src="app/static/logo.svg" width="112" alt="ArrMedic logo" />
</p>

<h1 align="center">ArrMedic</h1>
<p align="center"><strong>Your *Arr Stack Health Monitor</strong></p>
<p align="center">Diagnose · Monitor · Understand · Fix</p>

ArrMedic is a free, open-source diagnostics and troubleshooting dashboard for Sonarr, Radarr, Prowlarr, Lidarr, Readarr, Whisparr and the wider self-hosted media automation stack.

> **Current release: v0.5.0** — persistent multi-instance setup, encrypted API keys, live health scoring, application health checks, storage warnings, queue diagnostics, download-client visibility, Prowlarr indexer checks, remote-path mapping visibility, and the first working Path / Permission / Hardlink / Queue doctors.

## What ArrMedic does now

- Add multiple instances of Sonarr, Radarr, Prowlarr, Lidarr, Readarr and Whisparr
- Test every connection before saving it
- Automatically detect the API generation used by each supported *Arr app
- Encrypt API keys at rest
- Run one full-stack health scan from the browser
- Calculate a health score per service and for the whole stack
- Read native *Arr application health warnings
- Inspect root folders and free-space values
- Flag low storage (under 10 GiB on a reported root folder)
- Inspect queue/import state and surface useful error messages
- Show configured download clients
- Show remote-path mappings when exposed by the app
- Check enabled Prowlarr indexers
- Path Doctor: compare API paths with paths visible inside the ArrMedic container
- Permission Doctor: safely report ArrMedic container read visibility without pretending to know another container's UID/GID state
- Hardlink Doctor: detect when visible paths span filesystem/device boundaries that prevent hardlinks
- Queue Doctor: identify blocked/failed queue items
- Work normally even when no *Arr app has been added yet

## Docker

The official multi-architecture image (`linux/amd64` and `linux/arm64`) is:

```text
ghcr.io/kasundigital/arrmedic:latest
```

ArrMedic uses port `7080` everywhere: application, container and browser.

### Recommended Docker run

ArrMedic stores the administrator account, encrypted service API keys and SQLite database under `/config` inside the container. Keep that directory on the host with a bind mount:

```bash
sudo mkdir -p /opt/arrmedic/config

docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Open:

```text
http://SERVER-IP:7080
```

The application can be installed and explored immediately. Adding an *Arr service is optional.

### Optional: unlock deeper filesystem diagnostics

API diagnostics do **not** require media mounts. Path Doctor, Permission Doctor and Hardlink Doctor become more useful when ArrMedic can see the same paths that the *Arr apps report.

For example, if Sonarr/Radarr use `/data`:

```bash
docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --mount type=bind,source=/data,target=/data,readonly \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Read-only media mounts are recommended for diagnostics. ArrMedic v0.5 does not create test hardlinks or modify media files.

### Updating ArrMedic

Your configuration survives container replacement because `/config` lives on the host:

```bash
docker stop arrmedic
docker rm arrmedic
docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

If you use optional media mounts, include the same mounts again when recreating the container.

### Docker Compose

```yaml
services:
  arrmedic:
    image: ghcr.io/kasundigital/arrmedic:latest
    container_name: arrmedic
    pull_policy: always
    ports:
      - "7080:7080"
    volumes:
      - /opt/arrmedic/config:/config
      # Optional filesystem diagnostics:
      # - /data:/data:ro
    restart: unless-stopped
```

## Diagnostic API

Authenticated browser sessions can use:

```text
GET  /api/diagnostics/summary
GET  /api/instances/{id}/diagnostics
POST /api/instances/{id}/check
```

The full diagnostics endpoint intentionally treats unsupported APIs as unavailable rather than as failures. For example, Prowlarr does not have the same root-folder/queue model as Sonarr or Radarr.

## Build from source

```bash
git clone https://github.com/kasundigital/arrmedic.git
cd arrmedic
docker build -t arrmedic:local .
sudo mkdir -p /opt/arrmedic/config

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  arrmedic:local
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7080 --reload
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Next development

The next planned layers include download-client-specific deep checks (qBittorrent/SABnzbd/Transmission), richer path mapping analysis, history/event correlation, Bazarr/subtitle diagnostics, media stream inspection, notifications, exportable diagnostic reports and guided fixes.

## Security

ArrMedic does not require Docker socket access for normal operation. API keys are encrypted in `/config`; passwords are hashed. Never commit passwords, API keys or `.env` files to the repository.

Filesystem diagnostics are observational in v0.5. Read-only media mounts are sufficient and recommended.

## Contributing

Issues, feature requests and pull requests are welcome. The goal is to keep ArrMedic free, practical and friendly to self-hosted users.

## License

MIT License © 2026 Kasun Indika
