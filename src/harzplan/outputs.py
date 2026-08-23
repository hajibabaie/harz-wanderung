"""Step 5b: render plan.csv, one GPX per trip, the Folium map, progress.md."""
import csv
import json
from xml.sax.saxutils import escape

from . import config
from .network import load_stamps
from .rank import RANKED_PATH

OUT_DIR = config.ROOT / "output"

# Presentation only: distinct loop colours, repeating after 20 trips.
TRIP_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#aec7e8", "#ffbb78",
    "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2", "#dbdb8d",
    "#9edae5", "#393b79",
]


def trip_title(trip: dict, stamps: dict) -> str:
    """'Trip 03 – Prinzenlaube · Grumbacher Teich' (parking names are vague)."""
    names = " · ".join(stamps[n]["name"] for n in trip["stamps"])
    return f"Trip {trip['trip']:02d} – {names}"


def gpx_document(trip: dict, stamps: dict) -> str:
    th = trip["trailhead"]
    title = trip_title(trip, stamps)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" '
        'creator="harzplan">',
        f'  <wpt lat="{th["lat"]:.6f}" lon="{th["lon"]:.6f}">'
        f'<name>{escape("P " + th["name"])}</name><sym>Parking Area</sym></wpt>',
    ]
    for n in trip["stamps"]:
        s = stamps[n]
        parts.append(
            f'  <wpt lat="{s["lat"]:.6f}" lon="{s["lon"]:.6f}">'
            f'<name>{escape(f"HWN{n:03d} {s['name']}")}</name><sym>Flag</sym></wpt>'
        )
    parts.append(f'  <trk><name>{escape(title)}</name><trkseg>')
    parts += [
        f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>'
        for lat, lon in trip["geometry"]
    ]
    parts += ["  </trkseg></trk>", "</gpx>"]
    return "\n".join(parts)


def plan_row(trip: dict, stamps: dict) -> dict:
    hours, mins = divmod(round(trip["walk_min"]), 60)
    notes = []
    if trip.get("singleton"):
        notes.append("singleton")
    if trip.get("extended_km"):
        notes.append(f"extended +{trip['extended_km']} km")
    if trip.get("over_limit"):
        notes.append("over limit")
    if trip.get("under_min"):
        notes.append("under minimum")
    return {
        "trip": trip["trip"],
        "trailhead": trip["trailhead"]["name"],
        "trailhead_lat": round(trip["trailhead"]["lat"], 5),
        "trailhead_lon": round(trip["trailhead"]["lon"], 5),
        "drive_km": trip["drive_km"],
        "drive_min": round(trip["drive_min"]),
        "stamp_numbers": ";".join(str(n) for n in trip["stamps"]),
        "stamp_names": "; ".join(stamps[n]["name"] for n in trip["stamps"]),
        "loop_km": trip["loop_km"],
        "ascent_m": trip["ascent_m"],
        "walk_h": f"{hours}:{mins:02d}",
        "note": ", ".join(notes),
    }


def clear_trip_files(trips_dir) -> None:
    """Drop GPX files of the previous plan so numbering never leaves leftovers."""
    for old in trips_dir.glob("trip_*.gpx"):
        old.unlink()


def progress_lines(trips: list[dict], thresholds: list, done_count: int,
                   total: int) -> list[str]:
    lines = []
    cum = done_count
    for t in trips:
        before, cum = cum, cum + len(t["stamps"])
        stamps_txt = ", ".join(str(n) for n in t["stamps"])
        line = (f"- [ ] Trip {t['trip']:02d} — {t['trailhead']['name']} — "
                f"stamps {stamps_txt} — total {cum}/{total}")
        badges = [name for count, name in thresholds if before < count <= cum]
        if badges:
            line += f"  **← {', '.join(badges)}!**"
        lines.append(line)
    return lines


def build_map(trips: list[dict], stamps: dict, home: dict, max_points: int,
              unplanned: list[int]):
    import folium

    fmap = folium.Map(location=[home["lat"], home["lon"]], zoom_start=11)
    folium.Marker(
        [home["lat"], home["lon"]],
        tooltip=f"Home: {home['name']}",
        icon=folium.Icon(color="black", icon="home"),
    ).add_to(fmap)
    for t in trips:
        color = TRIP_COLORS[(t["trip"] - 1) % len(TRIP_COLORS)]
        geom = t["geometry"]
        step = max(1, len(geom) // max_points)
        pts = geom[::step]
        if pts[-1] != geom[-1]:
            pts.append(geom[-1])
        folium.PolyLine(
            pts, color=color, weight=3, opacity=0.8,
            tooltip=f"Trip {t['trip']:02d} — {t['loop_km']} km, {t['ascent_m']} m up",
        ).add_to(fmap)
        th = t["trailhead"]
        folium.Marker(
            [th["lat"], th["lon"]],
            icon=folium.Icon(color="gray", icon="car", prefix="fa"),
            tooltip=(f"Trip {t['trip']:02d}: {th['name']} "
                     f"(drive {round(t['drive_min'])} min)"),
        ).add_to(fmap)
        for n in t["stamps"]:
            s = stamps[n]
            folium.CircleMarker(
                [s["lat"], s["lon"]], radius=5, color=color, fill=True,
                fill_opacity=0.9,
                tooltip=f"HWN{n:03d} {s['name']} (Trip {t['trip']:02d})",
            ).add_to(fmap)
    for n in unplanned:
        s = stamps[n]
        folium.CircleMarker(
            [s["lat"], s["lon"]], radius=5, color="#555555", fill=True,
            tooltip=f"HWN{n:03d} {s['name']} (not planned yet)",
        ).add_to(fmap)
    return fmap


def main() -> None:
    cfg = config.load()
    data = json.loads(RANKED_PATH.read_text(encoding="utf-8"))
    trips, unroutable = data["trips"], data["unroutable"]
    stamps = {s["number"]: s for s in load_stamps()}
    trips_dir = OUT_DIR / "trips"
    trips_dir.mkdir(parents=True, exist_ok=True)
    clear_trip_files(trips_dir)

    rows = [plan_row(t, stamps) for t in trips]
    with open(OUT_DIR / "plan.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    for t in trips:
        path = trips_dir / f"trip_{t['trip']:02d}.gpx"
        path.write_text(gpx_document(t, stamps), encoding="utf-8")

    unplanned = [n for r in unroutable for n in r["stamps"]]
    fmap = build_map(trips, stamps, cfg["home"],
                     cfg["outputs"]["map_points_per_trip"], unplanned)
    fmap.save(str(OUT_DIR / "map.html"))

    done = cfg["progress"]["done"]
    lines = [
        "# Harzer Wandernadel — Saturday progress",
        "",
        "Tick a trip after hiking it, then add its stamp numbers to",
        "`[progress] done` in `config.toml` and re-run the pipeline.",
        "",
    ]
    trips_done = cfg["progress"]["trips_done"]
    if trips_done:
        lines.append(f"- [x] Trips 01–{trips_done:02d} — done — stamps "
                     f"{', '.join(str(n) for n in sorted(done))} — total "
                     f"{len(done)}/{cfg['data']['stamp_count']}")
    lines += progress_lines(trips, cfg["badges"]["thresholds"], len(done),
                            cfg["data"]["stamp_count"])
    if unplanned:
        lines += ["", "## Not planned yet (no reachable parking)", ""]
        lines += [f"- HWN{n:03d} {stamps[n]['name']}" for n in sorted(unplanned)]
    (OUT_DIR / "progress.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_DIR / 'plan.csv'} ({len(rows)} trips)")
    print(f"wrote {len(trips)} GPX files to {trips_dir}")
    print(f"wrote {OUT_DIR / 'map.html'} and {OUT_DIR / 'progress.md'}")


if __name__ == "__main__":
    main()
