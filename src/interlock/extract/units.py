"""Unit normalization via Pint, with engineering-unit aliases.

Pint already understands V, A, Hz, °C, F, Ω, etc. We add:
- '%' as a dimensionless 0.01 ratio (so "5.75 %" normalizes to 0.0575)
- 'kVA' and 'MVA' as voltampere prefixes (Pint covers volt_ampere but kVA/MVA aliases vary)
- 'μF' alias for microfarad

Bare numbers are treated as dimensionless.
"""

from __future__ import annotations

import pint

_ureg = pint.UnitRegistry()
# Pint already understands Ω, μF, kV, MVA, kVA, °C, etc. natively.
# Only '%' as a 0.01 dimensionless ratio needs adding.
_ureg.define("percent = 0.01 = %")


def parse_quantity(text: str) -> pint.Quantity:
    cleaned = text.strip().replace(",", "")
    return _ureg.Quantity(cleaned)


def normalize_quantity(text: str) -> pint.Quantity:
    return parse_quantity(text).to_base_units()


def equivalent(a: str, b: str, rel_tol: float = 1e-3) -> bool:
    try:
        qa = normalize_quantity(a)
        qb = normalize_quantity(b)
    except Exception:
        return False
    if qa.dimensionality != qb.dimensionality:
        return False
    mb = float(qb.magnitude)
    ma = float(qa.magnitude)
    if mb == 0:
        return ma == 0
    return abs(ma - mb) / abs(mb) <= rel_tol
