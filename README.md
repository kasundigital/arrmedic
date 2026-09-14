<p align="center">
  <img src="app/static/logo.svg" width="112" alt="ArrMedic logo" />
</p>

<h1 align="center">ArrMedic</h1>
<p align="center"><strong>Your *Arr Stack Health Monitor</strong></p>
<p align="center">Diagnose · Monitor · Understand · Fix</p>

ArrMedic is an open-source diagnostics and troubleshooting dashboard for Sonarr, Radarr, Prowlarr, Lidarr and the wider self-hosted media automation stack.

> Status: early development. ArrMedic includes first-run admin setup, persistent multi-instance configuration, service connection testing and the compact web dashboard. Path, permission, hardlink, storage and queue diagnostics are being added next.

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

### Recommended: Docker run with persistent bind mount

ArrMedic stores the administrator account, encrypted service API keys and application database under `/config` inside the container. The recommended Docker installation permanently binds that directory to `/opt/arrmedic/config` on the host.

Create the persistent directory once:

```bash
sudo mkdir -p /opt/arrmedic/config
```

Pull and start ArrMedic:

```bash
docker pull ghcr.io/kasundigital/arrmedic:latest

docker run -d \
  --name arrmedic \
  -p 7080:7080 \
  --mount type=bind,source=/opt/arrmedic/config,target=/config \
  --restart unless-stopped \
  ghcr.io/kasundigital/arrmedic:latest
```

Your persistent ArrMedic data will remain on the host at:

```text
/opt/arrmedic/config
```

This data survives `docker stop`, `docker rm`, image updates and container recreation.

Open:

```text
http://SERVER-IP:7080
```

### Updating ArrMedic

Because `/config` is bind-mounted to the host, you can safely replace the container:

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
    restart: unless-stopped
```

Then run:

```bash
sudo mkdir -p /opt/arrmedic/config
docker compose up -d
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

On Windows PowerShell, activate the virtual environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Security

ArrMedic should not require Docker socket access for normal use. If Docker-level diagnostics are introduced later, socket integration will be optional and documented separately.

Never commit API keys, passwords or `.env` files to the repository.

## Contributing

Issues, feature requests and pull requests are welcome. The goal is to keep ArrMedic free, practical and friendly to self-hosted users.

## License

MIT License © 2026 Kasun Indika
