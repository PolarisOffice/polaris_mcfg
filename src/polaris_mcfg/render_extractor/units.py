"""Pixel → font-unit conversion.

Two cases:

1. **UPM known.** The backend reports it (e.g., FreeType
   ``face.units_per_EM``) or the caller passes it. Then conversion is
   exact: ``font_unit = pixel * (upem / size_px)``.

2. **UPM unknown.** Browser backends generally can't expose UPM. We have
   two choices:
   - Pick a canonical UPM (1000) and report values in that frame. The
     downstream MetricsSpec carries ``unitsPerEm = 1000`` and consumers
     interpret everything in that frame.
   - Infer from cap height: typical cap height is 70~75% of UPM. With
     ``cap_height_px`` measured and assuming ``UPM = 1000``, we can
     verify or refine. We default to the canonical-1000 strategy because
     "the metric values look right in 1000 UPM" is what every downstream
     tool expects.

The conversion is rounded to the nearest integer because MetricsSpec
fields are typed ``int``.
"""
from __future__ import annotations


def pixel_to_unit(pixel: float, size_px: int, upem: int) -> int:
    """Convert a pixel measurement to font units, rounded to nearest int.

    At ``size_px == upem`` (the common 1000=1000 case) the conversion is
    the identity (modulo rounding).
    """
    if size_px <= 0:
        raise ValueError("size_px must be positive")
    if upem <= 0:
        raise ValueError("upem must be positive")
    return int(round(pixel * upem / size_px))


def pixel_to_unit_float(pixel: float, size_px: int, upem: int) -> float:
    """Like :func:`pixel_to_unit` but keeps fractional precision.

    Useful when downstream code does its own rounding (e.g., averaging
    multiple measurements before integerizing).
    """
    if size_px <= 0:
        raise ValueError("size_px must be positive")
    if upem <= 0:
        raise ValueError("upem must be positive")
    return pixel * upem / size_px
