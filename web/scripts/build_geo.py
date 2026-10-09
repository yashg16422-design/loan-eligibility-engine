"""Build web/public/geo/globe.json, the dotted globe's data, from Natural Earth (public domain).

Usage (from the repo root, with the Natural Earth GeoJSON files in DIR):
    python web/scripts/build_geo.py DIR web/public/geo/globe.json

Inputs, from naturalearthdata.com (converted to GeoJSON):
    ne_50m_land.geojson, ne_10m_admin_0_countries_ind.geojson (India point-of-view borders),
    ne_10m_populated_places_simple.geojson

Output: a JSON object of base64 little-endian Int16 arrays, values = degrees x 100:
    land    (lat, lon) land dots on a Fibonacci sphere, India removed (it has its own layer)
    india   (lat, lon) denser dots inside India
    guj     (lat, lon) densest dots around Surat, for the final zoom (the shader cross-fades it)
    cities  (lat, lon, weight) city lights; weight = log10(population) - 5

Needs numpy and Pillow. Not run in CI: the output is committed, this records how it was made.
"""

import base64
import json
import math
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

RES = 20  # land-mask pixels per degree (0.05 degree cells)
W, H = 360 * RES, 180 * RES
SURAT_BOX = ((19.2, 23.6), (70.4, 75.4))  # (lat range, lon range) of the densest layer


def outer_rings(geom: dict) -> Iterator[list]:
    """Outer ring of each polygon; holes are ignored (lakes don't matter at dot scale)."""
    if geom["type"] == "Polygon":
        yield geom["coordinates"][0]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield poly[0]


def mask_from(features: list[dict]) -> np.ndarray:
    """Rasterise polygons into an equirectangular boolean mask."""
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    for f in features:
        for ring in outer_rings(f["geometry"]):
            draw.polygon([((lon + 180) * RES, (90 - lat) * RES) for lon, lat in ring], fill=1)
    return np.array(img, dtype=bool)


def fibonacci(
    n: int, lat_rng: tuple[float, float] = (-90, 90), lon_rng: tuple[float, float] = (-180, 180)
) -> tuple[np.ndarray, np.ndarray]:
    """Points of an n-point Fibonacci sphere inside a lat/lon box, without building all n.

    Evenly spread dots are what make the globe read as a clean dot matrix, not noise.
    """
    golden = math.pi * (3 - math.sqrt(5))
    zmin, zmax = math.sin(math.radians(lat_rng[0])), math.sin(math.radians(lat_rng[1]))
    # z = 1 - 2(i + 0.5)/n, so a latitude band is a contiguous index range
    i0 = max(int((1 - zmax) * n / 2) - 1, 0)
    i1 = min(int((1 - zmin) * n / 2) + 1, n)
    i = np.arange(i0, i1, dtype=np.float64)
    lat = np.degrees(np.arcsin(1 - 2 * (i + 0.5) / n))
    lon = (np.degrees(i * golden) + 180) % 360 - 180
    keep = (lat >= lat_rng[0]) & (lat <= lat_rng[1]) & (lon >= lon_rng[0]) & (lon <= lon_rng[1])
    return lat[keep], lon[keep]


def inside(mask: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Which points fall on the mask."""
    x = np.clip(((lon + 180) * RES).astype(int), 0, W - 1)
    y = np.clip(((90 - lat) * RES).astype(int), 0, H - 1)
    return mask[y, x]


def b64(values: np.ndarray | list[int]) -> str:
    """Little-endian Int16 bytes as base64."""
    return base64.b64encode(np.asarray(values, dtype="<i2").tobytes()).decode()


def pack(lat: np.ndarray, lon: np.ndarray) -> str:
    """Interleave (lat, lon) x 100 as Int16."""
    return b64(np.stack([np.round(lat * 100), np.round(lon * 100)], 1).ravel())


def city_lights(features: list[dict]) -> list[int]:
    """Big cities worldwide, plus every Indian city over 150k so India glows on the zoom."""
    out: list[int] = []
    for f in features:
        p = f["properties"]
        pop = p.get("pop_max") or 0
        if pop >= 900_000 or (p.get("adm0_a3") == "IND" and pop >= 150_000):
            weight = math.log10(max(pop, 1)) - 5  # about 0..2.3
            out += [round(p["latitude"] * 100), round(p["longitude"] * 100), round(weight * 100)]
    return out


def main(src: Path, out: Path) -> None:
    """Read the Natural Earth files in src and write the globe JSON to out."""
    land = json.loads((src / "ne_50m_land.geojson").read_text())["features"]
    countries = json.loads((src / "ne_10m_admin_0_countries_ind.geojson").read_text())["features"]
    india = [f for f in countries if f["properties"]["NAME"] == "India"]
    places = json.loads((src / "ne_10m_populated_places_simple.geojson").read_text())["features"]
    land_m, india_m = mask_from(land), mask_from(india)

    lat, lon = fibonacci(110_000)
    keep = inside(land_m, lat, lon) & ~inside(india_m, lat, lon)
    data = {"land": pack(lat[keep], lon[keep])}

    lat, lon = fibonacci(900_000, (5, 38), (66, 99))
    keep = inside(india_m, lat, lon)
    data["india"] = pack(lat[keep], lon[keep])

    lat, lon = fibonacci(9_000_000, *SURAT_BOX)
    keep = inside(india_m, lat, lon)
    data["guj"] = pack(lat[keep], lon[keep])

    data["cities"] = b64(city_lights(places))
    out.write_text(json.dumps(data, separators=(",", ":")))
    sizes = {k: len(base64.b64decode(v)) // 2 for k, v in data.items()}
    print("int16 values per layer:", sizes, "bytes:", out.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
