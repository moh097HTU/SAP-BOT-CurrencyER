# routes/__init__.py
from fastapi import APIRouter
from . import auth
from . import currency
from .drafts import router as drafts_router
from .fallback import router as fallback_router   # <-- add this

router = APIRouter()
router.include_router(auth.router, tags=["auth"])
router.include_router(currency.router, tags=["currency"])
router.include_router(drafts_router, tags=["drafts"])
router.include_router(fallback_router, tags=["fallback"])  # <-- add this
