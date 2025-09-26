from __future__ import annotations

from pydantic import BaseModel, Field, validator
from decimal import Decimal, ROUND_HALF_UP


class ExchangeRateItem(BaseModel):
    ExchangeRateType: str = Field(..., description="e.g. M")
    FromCurrency: str = Field(..., description="e.g. USD")
    ToCurrency: str = Field(..., description="e.g. JOD")
    # Normalize to DD.MM.YYYY for SAP typing
    ValidFrom: str = Field(
        ...,
        description="Date like 31.12.2025 or 2025-12-31 or 12/31/2025; normalized to DD.MM.YYYY"
    )
    Quotation: str | None = Field("Direct", description="Direct or Indirect")
    ExchangeRate: str | float | Decimal = Field(..., description="> 0; rounded to 5 dp")

    @validator("ExchangeRateType", "FromCurrency", "ToCurrency")
    def _up(cls, v: str):  # noqa: N805
        return (v or "").strip().upper()

    @validator("Quotation", always=True)
    def _q(cls, v: str | None):  # noqa: N805
        s = (v or "Direct").strip().capitalize()
        return "Indirect" if s.startswith("Ind") else "Direct"

    @validator("ValidFrom")
    def _datefmt(cls, v: str):  # noqa: N805
        s = (v or "").strip()
        fmts = [
            "%m/%d/%Y",   # 12/31/2025
            "%Y-%m-%d",   # 2025-12-31
            "%Y/%m/%d",   # 2025/12/31
            "%d/%m/%Y",   # 31/12/2025
            "%Y%m%d",     # 20251231
            "%d.%m.%Y",   # 31.12.2025
            "%Y-%d-%m",   # legacy 2025-31-12
        ]
        from datetime import datetime as _dt
        for f in fmts:
            try:
                dt = _dt.strptime(s, f)
                return dt.strftime("%d.%m.%Y")
            except Exception:
                pass
        raise ValueError(f"Unrecognized date: {v}")

    @validator("ExchangeRate")
    def _5dp(cls, v):  # noqa: N805
        q = Decimal(str(v))
        if q <= 0:
            raise ValueError("ExchangeRate must be > 0")
        q = q.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        return f"{q:.5f}"
