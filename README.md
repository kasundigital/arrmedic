<p align="center">
  <img src="app/static/logo.svg" width="112" alt="ArrMedic logo" />
</p>

<h1 align="center">ArrMedic</h1>
<p align="center"><strong>Your *Arr Stack Health Monitor</strong></p>
<p align="center">Diagnose · Monitor · Understand · Fix</p>

ArrMedic is a free, open-source diagnostics and troubleshooting dashboard for Sonarr, Radarr, Prowlarr, Lidarr, Readarr, Whisparr and the wider self-hosted media automation stack.

> **Current release: v0.6.0** — live stack diagnostics, persisted scan history, recent failure correlation, prioritized guided fixes, JSON report export, multiple encrypted *Arr connections and a professional browser-first dashboard.

## What ArrMedic does now

- Add multiple instances of Sonarr, Radarr, Prowlarr, Lidarr, Readarr and Whisparr
- Test each connection before saving it
- Automatically detect supported API generation (`v1` / `v3` fallback)
- Encrypt API keys at rest and hash the administrator password
- Run and save a full-stack health scan
- Keep the latest **50 diagnostic scans** in persistent SQLite storage
- Show a health-history trend in the browser
- Calculate per-service and whole-stack health scores
- Read native *Arr application health warnings
- Correlate recent failure/error events from *Arr history (up to 24 hours)
- Inspect root folders and reported free space
- Flag root folders below 10 GiB free space
- Inspect queue/import failures and extract useful status messages
- Show configured download clients and remote-path mappings
- Check enabled Prowlarr indexers
- Generate prioritized **guided fixes** with concrete troubleshooting steps
- Export the current saved diagnostic report as JSON from the browser
- Work normally with zero *Arr services configured

## Working Doctors

**Path Doctor** compares paths reported by the *Arr API with paths visible inside ArrMedic. **Permission Doctor** checks ArrMedic's own read visibility without falsely claiming to know another container's UID/GID state. **Hardlink Doctor** detects visible paths on different filesystem/device boundaries. **Queue Doctor** identifies blocked/failed queue items and surfaces the useful error text.

Filesystem checks are observational. ArrMedic v0.6 does not modify media or create test hardlinks.

## Docker

Official multi-architecture image (`linux/amd64` and `linux/arm64`):

```text
ghcr.io/kasundigital/arrmedic:latest
```

ArrMedic uses **7080 everywhere**.

### Recommended plain Docker installation

Persistent data belongs on the host so container replacement never removes the login, encrypted API keys, settings or saved diagnostic history:

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

Creating an admin account is the only required first-run step. Connecting an *Arr app is optional and can be done later.

### Optional deeper filesystem diagnostics

API diagnostics work without media mounts. If Sonarr/Radarr report paths such as `/data`, mount the same path read-only into ArrMedic to unlock deeper Path / Permission / Hardlink checks:

```bash
docker stop arrmedic
docker rm arrmedic

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --mount type=bind,source=/data,target=/data,readonly \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Use the same container path that the relevant *Arr app reports. Read-only is sufficient.

### Updating

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

If you use optional media mounts, include them again when recreating the container.

## Diagnostic API

Authenticated sessions can use:

```text
GET  /api/diagnostics/summary            # live, unsaved scan
POST /api/diagnostics/run                # run + persist full scan
GET  /api/diagnostics/latest             # latest persisted result
GET  /api/diagnostics/history?limit=20   # saved score history
GET  /api/instances/{id}/diagnostics     # one service, not saved as full scan
POST /api/instances/{id}/check           # connection check
```

Unsupported endpoints on a particular service are treated as unavailable rather than automatically treated as failures.

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

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7080 --reload
```

Windows PowerShell activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Quality checks

CI runs Python tests, validates browser JavaScript syntax with Node, and builds the Docker image before changes are merged.

## Next development

Planned layers include deeper qBittorrent/SABnzbd/Transmission-specific checks, richer remote-path analysis, Bazarr/subtitle diagnostics, media stream inspection, notifications and additional safe guided remediation.

## Security

ArrMedic does not require Docker socket access for normal operation. API keys are encrypted in `/config`; passwords are hashed. Do not commit secrets, passwords, API keys or `.env` files.

## Contributing

Issues, feature requests and pull requests are welcome. The goal is to keep ArrMedic free, practical and friendly to self-hosted users.

## License

MIT License © 2026 Kasun Indika
