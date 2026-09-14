from pathlib import Path

from . import main as main_module
from .cleanup import router as cleanup_router
from .doctor import router as doctor_router

VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
RELEASE_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else main_module.APP_VERSION

main_module.APP_VERSION = RELEASE_VERSION
app = main_module.app
app.version = RELEASE_VERSION
app.include_router(cleanup_router)
app.include_router(doctor_router)

__all__ = ["app"]
