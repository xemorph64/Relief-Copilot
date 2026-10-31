"""GPS pin -> Maharashtra district, from the district TopoJSON in data/geo.

Boundaries are a community dataset (MIT, guneetnarula/indian-district-boundaries) used only to
suggest the district; the citizen confirms it.
"""
import json
from functools import lru_cache

from shapely.geometry import Point, Polygon, MultiPolygon

from app.config import ROOT

# dataset spelling -> current official name
ALIASES = {"Ahmadnagar": "Ahilyanagar", "Aurangabad": "Chhatrapati Sambhajinagar", "Osmanabad": "Dharashiv",
           "Bid": "Beed", "Raigarh": "Raigad", "Buldana": "Buldhana", "Gondiya": "Gondia"}


@lru_cache
def districts() -> list[tuple[str, object]]:
    t = json.loads((ROOT / "data" / "geo" / "maharashtra_districts.topo.json").read_text(encoding="utf-8"))
    (sx, sy), (tx, ty) = t["transform"]["scale"], t["transform"]["translate"]
    arcs = []
    for arc in t["arcs"]:  # delta-decode quantized arcs
        x = y = 0
        pts = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        pts = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts

    out = []
    for g in next(iter(t["objects"].values()))["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        shape = MultiPolygon([Polygon(ring(p[0]), [ring(h) for h in p[1:]]) for p in polys]).buffer(0)
        name = g["properties"]["district"]
        out.append((ALIASES.get(name, name), shape))
    return out


def district_at(lat: float, lon: float) -> str | None:
    p = Point(lon, lat)
    return next((n for n, s in districts() if s.contains(p)), None)


def all_districts() -> list[str]:
    return sorted(n for n, _ in districts())
