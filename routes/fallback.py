# routes/fallback.py
from __future__ import annotations

from datetime import datetime, date
from typing import Dict, Any, Optional

from fastapi import APIRouter, Query, HTTPException

from services.fallback_service import run_collect_missing_range

router = APIRouter(prefix="/currency/exchange-rates/fallback")


def _parse_iso(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=422, detail=f"Date must be YYYY-MM-DD, got {s!r}")


@router.post("/collect-missing")
async def collect_missing(
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    if not date_from or not date_to:
        raise HTTPException(
            status_code=400,
            detail="Provide ?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD",
        )

    df = _parse_iso(date_from)
    dt = _parse_iso(date_to)
    return run_collect_missing_range(df, dt)
