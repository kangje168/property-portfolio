import math
import re
from decimal import Decimal, InvalidOperation

from shapely.geometry import Point, Polygon

TYPES = {"apartment", "house", "office", "retail"}
COLUMNS = [
    "external_id",
    "name",
    "address",
    "city",
    "property_type",
    "bedrooms",
    "price_eur",
    "latitude",
    "longitude",
]


class Invalid(ValueError):
    pass


def integer(value, name, low=0, high=2147483647):
    raw = str(value) if value is not None else ""
    if isinstance(value, bool) or len(raw) > 10 or not re.fullmatch(r"[0-9]+", raw):
        raise Invalid(f"{name} must be an integer between {low} and {high}")
    number = int(value)
    if not low <= number <= high:
        raise Invalid(f"{name} must be an integer between {low} and {high}")
    return number


def text(value, name, limit):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise Invalid(f"{name} must contain 1–{limit} printable characters")
    return value.strip()


def money(value, name="price_eur"):
    if isinstance(value, bool) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,2})?", str(value)
    ):
        raise Invalid(
            f"{name} must be a nonnegative EUR amount with at most two decimals"
        )
    try:
        amount = Decimal(str(value))
        if amount > Decimal(1000000000):
            raise Invalid(f"{name} must not exceed 1000000000 EUR")
        return int(amount * 100)
    except InvalidOperation:
        raise Invalid(f"Invalid {name}") from None


def coordinate(value, name, low, high):
    try:
        if isinstance(value, bool):
            raise TypeError
        result = float(value)
        if not math.isfinite(result) or not low <= result <= high:
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise Invalid(f"{name} must be between {low} and {high}") from None


def property_row(row):
    result = {
        name: text(row.get(name), name, limit)
        for name, limit in [
            ("external_id", 80),
            ("name", 120),
            ("address", 240),
            ("city", 100),
        ]
    }
    if row.get("property_type") not in TYPES:
        raise Invalid("property_type must be apartment, house, office or retail")
    result.update(
        property_type=row["property_type"],
        bedrooms=integer(row.get("bedrooms"), "bedrooms", 0, 20),
        price_cents=money(row.get("price_eur")),
        latitude=coordinate(row.get("latitude"), "latitude", -90, 90),
        longitude=coordinate(row.get("longitude"), "longitude", -180, 180),
    )
    return result


def polygon_from(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"type", "coordinates"}
        or value.get("type") != "Polygon"
    ):
        raise Invalid("geometry must be a GeoJSON Polygon")
    rings = value["coordinates"]
    if not isinstance(rings, list) or not 1 <= len(rings) <= 10:
        raise Invalid("Polygon must contain an exterior ring and at most nine holes")
    count = 0
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            raise Invalid(
                "Every polygon ring must be closed and contain at least four positions"
            )
        for pair in ring:
            if not isinstance(pair, list) or len(pair) != 2:
                raise Invalid("Positions must be [longitude, latitude]")
            if any(type(n) not in (int, float) for n in pair):
                raise Invalid("Polygon positions must contain JSON numbers")
            coordinate(pair[0], "longitude", -180, 180)
            coordinate(pair[1], "latitude", -90, 90)
        count += len(ring)
    if count > 1000:
        raise Invalid("Polygon exceeds 1000 positions")
    polygon = Polygon(rings[0], rings[1:])
    if not polygon.is_valid or polygon.is_empty or polygon.area == 0:
        raise Invalid("Polygon is empty or self-intersecting")
    if polygon.bounds[2] - polygon.bounds[0] > 180:
        raise Invalid("Antimeridian-spanning polygons are not supported")
    return polygon


def in_polygon(polygon, longitude, latitude):
    return polygon.covers(Point(longitude, latitude))
