from harzplan import acquire

SAMPLE_GPX = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="test">
  <wpt lat="51.8416490" lon="10.5799757">
    <name>HWN001 Eckertalsperre</name>
    <desc>Eckertalsperre (Staumauer)</desc>
  </wpt>
  <wpt lat="51.7990000" lon="10.6156000">
    <name>HWN009 Brockenhaus</name>
    <desc>Brockenhaus</desc>
  </wpt>
  <wpt lat="51.0" lon="10.0">
    <name>Parkplatz Test</name>
  </wpt>
</gpx>
"""


def test_parse_gpx_extracts_stamps_and_skips_other_waypoints():
    stamps = acquire.parse_gpx(SAMPLE_GPX)
    assert len(stamps) == 2
    first = stamps[0]
    assert first["number"] == 1
    assert first["name"] == "Eckertalsperre"
    assert first["hint"] == "Eckertalsperre (Staumauer)"
    assert first["lat"] == 51.8416490
    assert first["lon"] == 10.5799757


def test_report_counts_and_missing():
    stamps = [{"number": 1}, {"number": 3}]
    text = acquire.report(stamps, expected=4)
    assert "recovered 2 of 4" in text
    assert "[2, 4]" in text


def test_report_flags_duplicates():
    stamps = [{"number": 1}, {"number": 1}]
    text = acquire.report(stamps, expected=2)
    assert "duplicate" in text


def test_geojson_sorted_by_number_lon_lat_order():
    stamps = [
        {"number": 5, "name": "B", "hint": "", "lat": 51.5, "lon": 10.5},
        {"number": 2, "name": "A", "hint": "x", "lat": 51.2, "lon": 10.2},
    ]
    gj = acquire.to_geojson(stamps)
    assert gj["type"] == "FeatureCollection"
    nums = [f["properties"]["number"] for f in gj["features"]]
    assert nums == [2, 5]
    assert gj["features"][0]["geometry"]["coordinates"] == [10.2, 51.2]
