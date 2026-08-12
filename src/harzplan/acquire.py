"""Step 1: fetch the official stamp list and write data/stamps.geojson."""
import io
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import config


def fetch_zip(url: str, cache_path: Path) -> bytes:
    """Download the official ZIP once; later runs read the cached copy."""
    if cache_path.exists():
        return cache_path.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=120).read()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(raw)
    return raw


def parse_gpx(gpx_bytes: bytes) -> list[dict]:
    root = ET.fromstring(gpx_bytes)
    ns = {"g": root.tag.split("}")[0].strip("{")}
    stamps = []
    for wpt in root.findall("g:wpt", ns):
        m = re.match(r"HWN(\d+)\s+(.*)", wpt.findtext("g:name", "", ns).strip())
        if not m:
            continue
        stamps.append({
            "number": int(m.group(1)),
            "name": m.group(2).strip(),
            "hint": wpt.findtext("g:desc", "", ns).strip(),
            "lat": float(wpt.get("lat")),
            "lon": float(wpt.get("lon")),
        })
    return stamps


def to_geojson(stamps: list[dict]) -> dict:
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {"number": s["number"], "name": s["name"], "hint": s["hint"]},
        }
        for s in sorted(stamps, key=lambda s: s["number"])
    ]
    return {"type": "FeatureCollection", "features": features}


def report(stamps: list[dict], expected: int) -> str:
    numbers = [s["number"] for s in stamps]
    found = set(numbers)
    missing = sorted(set(range(1, expected + 1)) - found)
    lines = [
        f"recovered {len(found)} of {expected} stamps",
        f"missing: {missing if missing else 'none'}",
    ]
    if len(numbers) != len(found):
        dupes = sorted(n for n in found if numbers.count(n) > 1)
        lines.append(f"duplicate numbers in source: {dupes}")
    return "\n".join(lines)


def main() -> None:
    cfg = config.load()
    raw = fetch_zip(cfg["data"]["gpx_url"], config.ROOT / "cache" / "hwn_gpx.zip")
    z = zipfile.ZipFile(io.BytesIO(raw))
    gpx_name = next(n for n in z.namelist() if n.lower().endswith(".gpx"))
    stamps = parse_gpx(z.read(gpx_name))
    out = config.ROOT / "data" / "stamps.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(to_geojson(stamps), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    print(report(stamps, cfg["data"]["stamp_count"]))


if __name__ == "__main__":
    main()
