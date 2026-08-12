import xml.etree.ElementTree as ET

from harzplan import outputs

TRIP = {
    "trip": 1,
    "stamps": [7],
    "trailhead": {"lat": 51.8, "lon": 10.3, "name": "Parkplatz Käste & Co"},
    "loop_km": 4.2,
    "ascent_m": 120,
    "drive_km": 5.0,
    "drive_min": 9.0,
    "walk_min": 62.0,
    "singleton": True,
    "geometry": [(51.8, 10.3), (51.81, 10.31), (51.8, 10.3)],
}
STAMPS = {7: {"number": 7, "name": "Käste & Haus", "lat": 51.81, "lon": 10.31}}


def test_gpx_document_has_track_and_waypoints_with_escaping():
    doc = outputs.gpx_document(TRIP, STAMPS)
    root = ET.fromstring(doc)  # parse fails on bad escaping
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    wpts = root.findall("g:wpt", ns)
    assert len(wpts) == 2  # trailhead + one stamp
    names = [w.findtext("g:name", "", ns) for w in wpts]
    assert "HWN007 Käste & Haus" in names
    assert len(root.findall(".//g:trkpt", ns)) == 3


def test_progress_lines_mark_badge_crossings():
    trips = [
        {"trip": 1, "stamps": [1, 2, 3, 4, 5], "trailhead": {"name": "A"}},
        {"trip": 2, "stamps": [6, 7, 8, 9], "trailhead": {"name": "B"}},
    ]
    lines = outputs.progress_lines(trips, [[8, "Bronze"]], done_count=0, total=222)
    assert lines[0].startswith("- [ ] Trip 01")
    assert "5/222" in lines[0]
    assert "Bronze" not in lines[0]
    assert "9/222" in lines[1]
    assert "Bronze" in lines[1]


def test_plan_row_flattens_trip_for_csv():
    row = outputs.plan_row(TRIP, STAMPS)
    assert row["trip"] == 1
    assert row["stamp_numbers"] == "7"
    assert row["stamp_names"] == "Käste & Haus"
    assert row["trailhead"] == "Parkplatz Käste & Co"
    assert row["walk_h"] == "1:02"
    assert row["note"] == "singleton"
