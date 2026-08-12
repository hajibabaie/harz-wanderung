import math

import networkx as nx
import numpy as np
import pytest

from harzplan import network


def test_compute_bbox_adds_buffer():
    west, south, east, north = network.compute_bbox(
        lats=[51.5, 51.9], lons=[10.4, 11.3], buffer_km=2.0
    )
    dlat = 2.0 / 110.574
    dlon = 2.0 / (111.320 * math.cos(math.radians(51.7)))
    assert south == pytest.approx(51.5 - dlat, abs=1e-6)
    assert north == pytest.approx(51.9 + dlat, abs=1e-6)
    assert west == pytest.approx(10.4 - dlon, abs=1e-4)
    assert east == pytest.approx(11.3 + dlon, abs=1e-4)


def test_dem_tile_names_covers_bbox():
    assert network.dem_tile_names((10.3, 51.45, 11.4, 51.95)) == [
        "N51_00_E010_00",
        "N51_00_E011_00",
    ]
    # A bbox dipping below 51N needs the N50 tiles too.
    assert "N50_00_E010_00" in network.dem_tile_names((10.3, 50.9, 11.4, 51.95))


def _toy_graph():
    """1 --1km-- 2 --1km-- 3, plus a slower 5km parallel edge 1-2.

    Node 4 is disconnected. Elevations: 100, 150, 120, 0.
    """
    G = nx.MultiDiGraph()
    for n, (lat, lon, elev) in {
        1: (51.80, 10.30, 100.0),
        2: (51.80, 10.31, 150.0),
        3: (51.80, 10.32, 120.0),
        4: (51.90, 10.90, 0.0),
    }.items():
        G.add_node(n, y=lat, x=lon, elevation=elev)
    for u, v, length in [(1, 2, 1000.0), (2, 3, 1000.0), (1, 2, 5000.0)]:
        G.add_edge(u, v, length=length)
        G.add_edge(v, u, length=length)
    return G


def test_stamp_matrices_distance_uses_shortest_parallel_edge():
    numbers, dist, ascent = network.stamp_matrices(
        _toy_graph(), {7: 1, 8: 3}, limit_m=float("inf")
    )
    assert numbers == [7, 8]
    assert dist[0, 0] == 0.0
    assert dist[0, 1] == pytest.approx(2000.0)
    assert dist[1, 0] == pytest.approx(2000.0)


def test_stamp_matrices_ascent_is_directional():
    _, _, ascent = network.stamp_matrices(
        _toy_graph(), {7: 1, 8: 3}, limit_m=float("inf")
    )
    # 1 -> 2 climbs 50 m, 2 -> 3 descends: ascent 1->3 is 50.
    assert ascent[0, 1] == pytest.approx(50.0)
    # 3 -> 2 climbs 30 m, 2 -> 1 descends: ascent 3->1 is 30.
    assert ascent[1, 0] == pytest.approx(30.0)


def test_stamp_matrices_limit_and_unreachable_are_inf():
    numbers, dist, _ = network.stamp_matrices(
        _toy_graph(), {7: 1, 8: 3, 9: 4}, limit_m=1500.0
    )
    assert numbers == [7, 8, 9]
    assert np.isinf(dist[0, 1])  # 2000 m > 1500 m limit
    assert np.isinf(dist[0, 2])  # node 4 is disconnected


def test_walk_path_follows_predecessors_from_source_to_target():
    pred = np.array([-9999, 0, 1])
    assert network.walk_path(pred, 0, 2) == [0, 1, 2]


def test_snap_stamps_picks_nearest_node_with_distance():
    G = _toy_graph()
    stamps = [{"number": 42, "lat": 51.8001, "lon": 10.31}]
    snapped = network.snap_stamps(G, stamps)
    node, dist_m = snapped[42]
    assert node == 2
    assert dist_m == pytest.approx(11.1, rel=0.05)  # ~0.0001 deg lat


def test_add_elevations_samples_raster(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    # 10x10 raster over lon 10..11, lat 51..52; value = row index.
    data = np.repeat(np.arange(10, dtype="float32"), 10).reshape(10, 10)
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", transform=from_origin(10.0, 52.0, 0.1, 0.1),
    ) as ds:
        ds.write(data, 1)

    G = nx.MultiDiGraph()
    G.add_node(1, y=51.95, x=10.05)  # top row -> value 0
    G.add_node(2, y=51.05, x=10.95)  # bottom row -> value 9
    network.add_elevations(G, [path])
    assert G.nodes[1]["elevation"] == pytest.approx(0.0)
    assert G.nodes[2]["elevation"] == pytest.approx(9.0)
