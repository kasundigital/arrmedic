from pathlib import Path

from . import main as main_module
from .cleanup import router as cleanup_router
from .deep_scan import install_auto_scan_middleware, install_deep_scan
from .doctor import router as doctor_router
from .download_doctor import router as download_doctor_router
from .hostfs import install_host_filesystem

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
RELEASE_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else main_module.APP_VERSION

main_module.APP_VERSION = RELEASE_VERSION
app = main_module.app
app.version = RELEASE_VERSION

# Prefer a read-only host-root mirror mounted at /host for filesystem checks.
# This lets ArrMedic inspect paths reported as /mnt/..., /downloads, /apps/...
# without granting write access to the host.
install_host_filesystem(main_module)

# Upgrade every existing diagnostic path to the deep read-only scanner before
# the API routers are exposed. This keeps single-instance, full-stack and
# automatic post-add scans consistent.
install_deep_scan(main_module)
install_auto_scan_middleware(app, main_module)

app.include_router(cleanup_router)
app.include_router(doctor_router)
app.include_router(download_doctor_router)

__all__ = ["app"]
