from pathlib import Path

from . import main as main_module
from .cleanup import router as cleanup_router
from .deep_scan import install_auto_scan_middleware, install_deep_scan
from .doctor import router as doctor_router
from .download_doctor import router as download_doctor_router

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
RELEASE_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else main_module.APP_VERSION

main_module.APP_VERSION = RELEASE_VERSION
app = main_module.app
app.version = RELEASE_VERSION

# Upgrade every existing diagnostic path to the deep read-only scanner before
# the API routers are exposed. This keeps single-instance, full-stack and
# automatic post-add scans consistent.
install_deep_scan(main_module)
install_auto_scan_middleware(app, main_module)

app.include_router(cleanup_router)
app.include_router(doctor_router)
app.include_router(download_doctor_router)

__all__ = ["app"]
