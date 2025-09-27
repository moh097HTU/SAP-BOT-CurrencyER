# routes/drafts.py
from __future__ import annotations

from datetime import datetime, date
from typing import Dict, Any, Optional

from fastapi import APIRouter, Query, Body, HTTPException
from pydantic import BaseModel

from services.drafts_service import run_delete_drafts_range

# Mount under /currency/exchange-rates
router = APIRouter(prefix="/currency/exchange-rates")

# ---------- Helpers ----------
def _parse_iso(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(status_code=422, detail=f"Date must be YYYY-MM-DD, got {s!r}")

class DeleteDraftsRequest(BaseModel):
    day_from: str  # "YYYY-MM-DD"
    day_to: str    # "YYYY-MM-DD"

# ---------- Unified endpoint (query OR body) ----------
@router.post("/drafts/delete")
async def delete_drafts(
    # Query style: /currency/exchange-rates/drafts/delete?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str]   = Query(default=None),
    # Body style: {"day_from":"YYYY-MM-DD","day_to":"YYYY-MM-DD"}
    body: Optional[DeleteDraftsRequest] = Body(default=None),
) -> Dict[str, Any]:

    # Prefer explicit query params if provided; else fall back to JSON body
    if date_from and date_to:
        df = _parse_iso(date_from)
        dt = _parse_iso(date_to)
    elif body is not None:
        df = _parse_iso(body.day_from)
        dt = _parse_iso(body.day_to)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either query params (?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD) "
                   "or JSON body {\"day_from\":\"YYYY-MM-DD\",\"day_to\":\"YYYY-MM-DD\"}."
        )

    # Run the deletion (inclusive). If df == dt, only that day is processed.
    return run_delete_drafts_range(df, dt)
