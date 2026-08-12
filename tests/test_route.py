import networkx as nx
import numpy as np
import pytest

from harzplan import network, route


def line_dist_m(points_km):
    pts = np.array(points_km, dtype=float) * 1000
    return np.abs(pts[:, None] - pts[None, :])


def test_orient_loop_walks_cheaper_direction():
    A = np.array([[0, 100, 0], [0, 0, 100], [50, 0, 0]], dtype=float)
    order, ascent = route.orient_loop([0, 1, 2], A)
    assert order == [0, 2, 1]
    assert ascent == pytest.approx(0.0)


def test_orient_loop_keeps_forward_when_already_cheaper():
    A = np.array([[0, 0, 50], [100, 0, 0], [0, 100, 0]], dtype=float)
    order, ascent = route.orient_loop([0, 1, 2], A)
    assert order == [0, 1, 2]
    assert ascent == pytest.approx(0.0)


def test_best_trailhead_picks_shorter_loop():
    # candidates at km 0 and 7; stamps at km 4 and 6
    D = line_dist_m([0.0, 7.0, 4.0, 6.0])
    A = np.zeros_like(D)
    cand, order, loop_m, ascent = route.best_trailhead(D, A, n_cand=2)
    assert cand == 1
    assert order[0] == 1
    assert set(order) == {1, 2, 3}
    assert loop_m == pytest.approx(6000.0)
    assert ascent == pytest.approx(0.0)


def test_best_trailhead_skips_unreachable_candidate():
    D = line_dist_m([0.0, 7.0, 4.0, 6.0])
    D[1, :] = D[:, 1] = np.inf
    D[1, 1] = 0.0
    A = np.zeros_like(D)
    cand, order, loop_m, _ = route.best_trailhead(D, A, n_cand=2)
    assert cand == 0
    assert loop_m == pytest.approx(12000.0)


def _chain_graph():
    G = nx.MultiDiGraph()
    for n, (lat, lon) in {1: (51.80, 10.30), 2: (51.80, 10.31), 3: (51.80, 10.32)}.items():
        G.add_node(n, y=lat, x=lon, elevation=0.0)
    for u, v in [(1, 2), (2, 3)]:
        G.add_edge(u, v, length=1000.0)
        G.add_edge(v, u, length=1000.0)
    return G


def test_loop_geometry_closes_the_loop():
    G = _chain_graph()
    A, nodes, idx, elev = network.build_csr(G)
    src_idx = [idx[1], idx[3]]
    _, _, preds = network.pairwise(A, elev, src_idx, limit_m=np.inf, want_pred=True)
    coords = route.loop_geometry([0, 1], src_idx, preds, nodes, G)
    assert coords[0] == coords[-1]
    assert len(coords) == 5  # 1-2-3-2-1
    assert coords[2] == (51.80, 10.32)
