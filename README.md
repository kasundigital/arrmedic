<p align="center">
  <img src="app/static/logo.svg" width="112" alt="ArrMedic logo" />
</p>

<h1 align="center">ArrMedic</h1>
<p align="center"><strong>Your *Arr Stack Health Monitor</strong></p>
<p align="center">Diagnose · Monitor · Understand · Fix</p>

ArrMedic is an open-source diagnostics and troubleshooting dashboard for Sonarr, Radarr, Prowlarr, Lidarr and the wider self-hosted media automation stack.

> Status: early v0.1 foundation. The current build includes the web dashboard, API health endpoint and live *Arr API connection testing. Path, permission, hardlink, storage and queue diagnostics are next.

## Why ArrMedic?

Media automation failures often involve several services at once: download clients, *Arr apps, Docker mounts, filesystem permissions and storage. ArrMedic aims to explain the actual cause in one place instead of making users read logs across every container.

Planned diagnostics include:

- Multiple Sonarr and Radarr instances
- API and service health checks
- Path mapping analysis
- Hardlink capability testing
- UID/GID and permission checks
- Storage and free-space warnings
- Queue/import problem explanations
- Prowlarr/indexer health
- qBittorrent, SABnzbd and Transmission checks
- Bazarr/subtitle diagnostics
- Language/media stream inspection
- Jellyfin/Plex compatibility checks

## Docker

The official image is published automatically to GitHub Container Registry for both `linux/amd64` and `linux/arm64`:

```text
ghcr.io/kasundigital/arrmedic:latest
```

ArrMedic uses port `7080` everywhere: application, container, Docker mapping, and browser access.

### Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  arrmedic:
    image: ghcr.io/kasundigital/arrmedic:latest
    container_name: arrmedic
    ports:
      - "7080:7080"
    volumes:
      - ./config:/config
    restart: unless-stopped
```

Then run:

```bash
docker compose pull
docker compose up -d
```

Open:

```text
http://SERVER-IP:7080
```

### Docker run

```bash
docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  -v ./config:/config \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

## Build from source

```bash
git clone https://github.com/kasundigital/arrmedic.git
cd arrmedic
docker build -t arrmedic:local .
docker run -d --name arrmedic -p 7080:7080 -v ./config:/config arrmedic:local
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 7080 --reload
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Current API

```text
GET  /api/health
POST /api/instances/test
```

Example connection-test body:

```json
{
  "kind": "sonarr",
  "url": "http://sonarr:8989",
  "api_key": "YOUR_API_KEY"
}
```

API keys submitted to the current test endpoint are not persisted. Persistent encrypted instance configuration will be added before stored connections are introduced.

## Development roadmap

### v0.1

- [x] FastAPI foundation
- [x] Responsive web dashboard
- [x] Health endpoint
- [x] Sonarr/Radarr/Prowlarr/Lidarr connection test
- [x] Docker + Compose
- [x] CI smoke tests
- [x] Automatic multi-architecture Docker publishing to GHCR
- [ ] Persistent multi-instance configuration
- [ ] Health score engine
- [ ] Root-folder and storage overview

### v0.2

- [ ] Path Doctor
- [ ] Hardlink Doctor
- [ ] Permission Doctor
- [ ] Queue Doctor

### v0.3+

- [ ] Download clients and Prowlarr
- [ ] Bazarr and language scanner
- [ ] Plex/Jellyfin media compatibility
- [ ] Notifications and safe guided fixes

## Security

ArrMedic should not require Docker socket access for normal use. If Docker-level diagnostics are introduced later, socket integration will be optional and documented separately.

Never commit API keys, passwords or `.env` files to the repository.

## Contributing

Issues, feature requests and pull requests are welcome. The goal is to keep ArrMedic free, practical and friendly to self-hosted users.

## License

MIT License © 2026 Kasun Indika
