import numpy as np
import pytest

from harzplan import cluster

TRIP = {
    "loop_km_min": 10.0,
    "loop_km_max": 18.0,
    "ascent_m_max": 600,
    "stamps_min": 2,
    "stamps_ideal_min": 3,
    "stamps_ideal_max": 5,
    "trailhead_reserve_km": 2.0,
}


def line_dist(points_km):
    pts = np.array(points_km, dtype=float) * 1000
    return np.abs(pts[:, None] - pts[None, :])


def test_tsp_tour_finds_square_perimeter():
    s = 1000.0
    d = s * 2**0.5
    D = np.array([[0, s, d, s], [s, 0, s, d], [d, s, 0, s], [s, d, s, 0]])
    order, length = cluster.tsp_tour(D)
    assert length == pytest.approx(4 * s)
    assert sorted(order) == [0, 1, 2, 3]


def test_tour_ascent_picks_cheaper_direction():
    A = np.array([[0, 100, 0], [0, 0, 100], [50, 0, 0]], dtype=float)
    # forward 0-1-2-0 climbs 250 m, reverse 0-2-1-0 climbs 0 m
    assert cluster.tour_ascent([0, 1, 2], A) == pytest.approx(0.0)


def test_split_pair_separates_around_farthest_stamps():
    D = line_dist([0, 4, 8, 12, 16, 20])
    a, b = cluster.split_pair([0, 1, 2, 3, 4, 5], D)
    halves = sorted([sorted(a), sorted(b)])
    assert halves == [[0, 1, 2], [3, 4, 5]]


def test_build_clusters_groups_and_flags_singleton():
    numbers = [1, 2, 3, 4, 5, 6, 7]
    D = line_dist([0, 2, 4, 30, 32, 34, 100])
    out = cluster.build_clusters(numbers, D, np.zeros_like(D), TRIP)
    got = sorted(sorted(c["stamps"]) for c in out)
    assert got == [[1, 2, 3], [4, 5, 6], [7]]
    by_first = {c["stamps"][0]: c for c in out}
    assert by_first[7]["singleton"] is True
    triple = next(c for c in out if sorted(c["stamps"]) == [1, 2, 3])
    assert triple["singleton"] is False
    assert triple["est_loop_km"] == pytest.approx(8.0)


def test_build_clusters_splits_oversize_group():
    numbers = [1, 2, 3, 4, 5, 6]
    D = line_dist([0, 1, 2, 3, 4, 5])
    out = cluster.build_clusters(numbers, D, np.zeros_like(D), TRIP)
    sizes = sorted(len(c["stamps"]) for c in out)
    assert max(sizes) <= TRIP["stamps_ideal_max"]
    assert sum(sizes) == 6


def test_build_clusters_unreachable_stamps_stay_singleton():
    numbers = [1, 2]
    D = np.array([[0.0, np.inf], [np.inf, 0.0]])
    out = cluster.build_clusters(numbers, D, np.zeros_like(D), TRIP)
    assert sorted(c["stamps"] for c in out) == [[1], [2]]
    assert all(c["singleton"] for c in out)


def test_build_clusters_survives_limit_truncated_pairs():
    # The Dijkstra limit truncates long pairs to inf, so a merge candidate
    # can have a finite gap while another cross-pair is infinite.
    numbers = [1, 2, 3]
    D = line_dist([0, 7, 33])
    D[D > 30000] = np.inf
    out = cluster.build_clusters(numbers, D, np.zeros((3, 3)), TRIP)
    total = sorted(n for c in out for n in c["stamps"])
    assert total == [1, 2, 3]


def test_build_clusters_respects_ascent_cap():
    numbers = [1, 2, 3]
    D = line_dist([0, 1, 2])
    A = np.full((3, 3), 400.0)
    np.fill_diagonal(A, 0.0)
    # every tour direction climbs 1200 m > 600 m cap -> must split
    out = cluster.build_clusters(numbers, D, A, TRIP)
    assert max(len(c["stamps"]) for c in out) < 3
