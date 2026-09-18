<p align="center">
  <img src="app/static/logo.svg" width="112" alt="ArrMedic logo" />
</p>

<h1 align="center">ArrMedic</h1>
<p align="center"><strong>Your *Arr Stack Health Monitor</strong></p>
<p align="center">Diagnose · Monitor · Understand · Fix</p>

ArrMedic is a free, open-source diagnostics and troubleshooting dashboard for Sonarr, Radarr, Prowlarr, Lidarr, Readarr, Whisparr and the wider self-hosted media automation stack.

> **Current development release: v0.11.0** — automatic deep read-only diagnostics, downloader/path correlation, filesystem visibility, permission signals, health scoring, guided fixes, scan history and safe Docker mount suggestions.

## What ArrMedic checks

When you add or update a supported app, ArrMedic can automatically run a deep read-only scan and inspect as many capabilities as that app exposes safely through its API.

Checks include:

- API connection and application version
- Native *Arr health warnings
- Root folders and free space
- Disk-space warnings
- Queue and import failures
- Download clients
- Remote Path Mappings
- Radarr/Sonarr downloader path mismatches
- Indexer configuration
- Recent failure/error history
- Missing monitored media count when supported
- Media Management / hardlink settings when supported
- Host path visibility
- Read permission visibility
- Native permission/access errors reported by the application
- Filesystem/device boundaries for hardlink compatibility
- Prowlarr connected applications
- Guided fixes and health scoring

Unsupported API endpoints are treated as unavailable capabilities, not as failures.

## Host filesystem diagnostics

For useful path, permission, storage and hardlink diagnostics, ArrMedic should have a **read-only view of the host filesystem**.

The standard layout is:

```text
/config  -> writable ArrMedic data
/host    -> read-only mirror of host /
```

The host root is mounted like this:

```bash
--mount type=bind,source=/,target=/host,readonly
```

ArrMedic then translates paths reported by apps automatically. For example:

```text
Radarr reports:       /mnt/Movies
ArrMedic checks:      /host/mnt/Movies

Sonarr reports:       /downloads/tv
ArrMedic checks:      /host/downloads/tv
```

This lets ArrMedic inspect whether the host path exists, whether it is readable, what filesystem/device it belongs to and how much space is available, without giving ArrMedic write access to the host.

> Do **not** mount host `/` onto container `/`. The host root must be mounted to `/host` so it does not replace the container filesystem.

The default host prefix is `/host`. Advanced users can override it with:

```text
ARRMEDIC_HOST_ROOT=/host
```

## Docker

Official multi-architecture image (`linux/amd64` and `linux/arm64`):

```text
ghcr.io/kasundigital/arrmedic:latest
```

ArrMedic uses **7080 everywhere**.

### Recommended plain Docker installation

```bash
sudo mkdir -p /opt/arrmedic/config

docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  -e ARRMEDIC_HOST_ROOT=/host \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --mount type=bind,source=/,target=/host,readonly \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Open:

```text
http://SERVER-IP:7080
```

The `/config` mount is writable and stores the login, encrypted API keys, settings and scan history. The `/host` mount is read-only and is used only for diagnostics.

### Docker Compose

```yaml
services:
  arrmedic:
    image: ghcr.io/kasundigital/arrmedic:latest
    container_name: arrmedic
    ports:
      - "7080:7080"
    environment:
      - ARRMEDIC_HOST_ROOT=/host
    volumes:
      - /opt/arrmedic/config:/config
      - /:/host:ro
    restart: unless-stopped
```

## Updating / reinstalling without losing settings

```bash
docker stop arrmedic 2>/dev/null || true
docker rm arrmedic 2>/dev/null || true

docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  -e ARRMEDIC_HOST_ROOT=/host \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --mount type=bind,source=/,target=/host,readonly \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Do not delete `/opt/arrmedic/config` if you want to keep your existing ArrMedic configuration.

## Why `/host` is read-only

ArrMedic is a diagnostics tool. It should be able to **observe** the host filesystem without being able to modify media, Docker application data or system files.

The host-root mount is therefore documented as read-only:

```text
/:/host:ro
```

ArrMedic does not require `/var/run/docker.sock` for normal diagnostics.

A read-only host mount still does **not** mean ArrMedic can know the exact effective UID/GID permissions inside another container. It can detect host path visibility/readability, filesystem layout and native permission errors reported by Radarr/Sonarr/etc., but it does not pretend to have visibility it does not actually have.

## Working Doctors

**Path Doctor** checks API paths against the host filesystem mirror. **Permission Doctor** checks readable paths and correlates native application access errors. **Hardlink Doctor** checks filesystem/device boundaries. **Queue Doctor** surfaces blocked imports and useful error messages. **Download Client Doctor** correlates Radarr/Sonarr queue paths, download clients and Remote Path Mappings.

Filesystem checks are observational. ArrMedic does not create test hardlinks or modify media during diagnostics.

## Diagnostic API

Authenticated sessions can use:

```text
GET  /api/diagnostics/summary            # live, unsaved deep scan
POST /api/diagnostics/run                # run + persist full scan
GET  /api/diagnostics/latest             # latest persisted result
GET  /api/diagnostics/history?limit=20   # saved score history
GET  /api/instances/{id}/diagnostics     # one service deep scan
POST /api/instances/{id}/check           # connection check
GET  /api/doctors/download-clients       # downloader/path correlation
```

## Build from source

```bash
git clone https://github.com/kasundigital/arrmedic.git
cd arrmedic
docker build -t arrmedic:local .
sudo mkdir -p /opt/arrmedic/config

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  -e ARRMEDIC_HOST_ROOT=/host \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --mount type=bind,source=/,target=/host,readonly \
  arrmedic:local
```

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.bootstrap:app --host 0.0.0.0 --port 7080 --reload
```

Windows PowerShell activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Quality checks

CI runs Python tests, validates browser JavaScript syntax with Node and builds the Docker image before changes are merged.

## Security

- `/config` is the only standard writable persistent mount.
- `/host` is mounted read-only for diagnostics.
- Docker socket access is not required by default.
- API keys are encrypted at rest.
- Administrator passwords are hashed.
- Do not commit secrets, passwords, API keys or `.env` files.

## Contributing

Issues, feature requests and pull requests are welcome. The goal is to keep ArrMedic free, practical and friendly to self-hosted users.

## License

MIT License © 2026 Kasun Indika

---

## ☕ Support this project

This project is free and open source. If it helps you, you can support continued development:

<div align="center">
  <a href="https://buymeacoffee.com/kasundigital" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="50">
  </a>
</div>
