from .main import app
from .cleanup import router as cleanup_router

app.include_router(cleanup_router)

__all__ = ["app"]
