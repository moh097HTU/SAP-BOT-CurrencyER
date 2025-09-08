from fastapi import APIRouter
from . import auth
from . import currency

router = APIRouter()
router.include_router(auth.router, tags=["auth"])
router.include_router(currency.router, tags=["currency"])
