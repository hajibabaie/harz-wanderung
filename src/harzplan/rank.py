"""Step 5a: drive times from home, walking times, and the Saturday order.

Early Saturdays get the short drives; the drive grows with the trip number.
Drive times come from the public OSRM demo server, cached per trailhead.
"""
import json
import urllib.request

from . import config
from .route import ROUTES_PATH

RANKED_PATH = config.ROOT / "cache" / "ranked.json"
DRIVES_PATH = config.ROOT / "cache" / "drives.json"


def walk_minutes(loop_km: float, ascent_m: float, tcfg: dict) -> float:
    """Naismith base time plus climb, with the Langmuir descent correction.

    On a closed loop the descent equals the ascent.
    """
    minutes = 60.0 * loop_km / tcfg["walk_speed_kmh"]
    minutes += ascent_m / 100.0 * tcfg["climb_min_per_100m"]
    minutes += ascent_m / 300.0 * tcfg["gentle_descent_min_per_300m"]
    return minutes


def osrm_table_url(base: str, coords: list[tuple]) -> str:
    """OSRM table request: first coordinate is the source, rest are targets."""
    pts = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)
    return f"{base}/table/v1/driving/{pts}?sources=0&annotations=duration,distance"


def fetch_drives(home: dict, trailheads: list[dict], osrm: dict) -> list[dict]:
    """Drive km/minutes from home to every trailhead, cached by coordinate."""
    cache = {}
    if DRIVES_PATH.exists():
        cache = json.loads(DRIVES_PATH.read_text(encoding="utf-8"))

    def key(p: dict) -> str:
        return f"{p['lat']:.5f},{p['lon']:.5f}"

    missing = list({key(p): p for p in trailheads if key(p) not in cache}.values())
    for start in range(0, len(missing), osrm["chunk_size"]):
        chunk = missing[start:start + osrm["chunk_size"]]
        coords = [(home["lon"], home["lat"])]
        coords += [(p["lon"], p["lat"]) for p in chunk]
        url = osrm_table_url(osrm["base_url"], coords)
        req = urllib.request.Request(
            url, headers={"User-Agent": "harz-wanderung-planner/0.1"}
        )
        data = json.load(urllib.request.urlopen(req, timeout=120))
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM error: {data.get('code')} {data.get('message')}")
        durations = data["durations"][0]
        distances = data["distances"][0]
        for i, p in enumerate(chunk, start=1):
            if durations[i] is None:
                print(f"WARNING no driving route to {p['name']} {key(p)}")
                cache[key(p)] = {"drive_km": float("inf"), "drive_min": float("inf")}
            else:
                cache[key(p)] = {
                    "drive_km": distances[i] / 1000.0,
                    "drive_min": durations[i] / 60.0,
                }
        DRIVES_PATH.write_text(json.dumps(cache), encoding="utf-8")
    return [cache[key(p)] for p in trailheads]


def rank_trips(trips: list[dict], start: int = 1) -> list[dict]:
    """Shortest drive first; numbering continues after the finished trips."""
    ranked = sorted(trips, key=lambda t: (t["drive_min"], t["stamps"][0]))
    return [{**t, "trip": i} for i, t in enumerate(ranked, start=start)]


def stamps_in_first_n(trips: list[dict], n: int) -> int:
    return sum(len(t["stamps"]) for t in trips[:n])


def main() -> None:
    cfg = config.load()
    if RANKED_PATH.exists():
        print(f"{RANKED_PATH} already exists — nothing to do")
        return
    routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    routable = [r for r in routes if "loop_km" in r]
    unroutable = [r for r in routes if "loop_km" not in r]
    drives = fetch_drives(cfg["home"], [r["trailhead"] for r in routable], cfg["osrm"])
    trips = [
        {
            **r,
            "drive_km": round(d["drive_km"], 1),
            "drive_min": round(d["drive_min"], 1),
            "walk_min": round(walk_minutes(r["loop_km"], r["ascent_m"], cfg["time"])),
        }
        for r, d in zip(routable, drives)
    ]
    ranked = rank_trips(trips, start=cfg["progress"]["trips_done"] + 1)
    RANKED_PATH.write_text(
        json.dumps({"trips": ranked, "unroutable": unroutable}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {RANKED_PATH}")
    print(f"{len(ranked)} trips ranked, numbered {ranked[0]['trip']}-{ranked[-1]['trip']}; "
          f"the first 8 cover {stamps_in_first_n(ranked, 8)} stamps")
    print(f"drive minutes: next trip = {ranked[0]['drive_min']:.0f}, "
          f"last = {ranked[-1]['drive_min']:.0f}")


if __name__ == "__main__":
    main()
