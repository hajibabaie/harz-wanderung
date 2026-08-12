"""Step 3: group stamps into clusters that work as one Saturday loop.

Complete-linkage clustering on the network distance matrix gives starting
groups, a split pass breaks groups that are too big, too long, or too steep,
and a merge pass grows groups that are too small or too short. Stamps that
fit nowhere stay as flagged singletons.
"""
import json
from itertools import permutations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from . import config
from .network import MATRIX_PATH

CLUSTERS_PATH = config.ROOT / "cache" / "clusters.json"
UNREACH_M = 1e7  # stands in for infinity inside linkage


def tsp_tour(D: np.ndarray) -> tuple[list[int], float]:
    """Exact shortest closed tour by brute force (cluster sizes are tiny)."""
    k = len(D)
    if k == 1:
        return [0], 0.0
    if k == 2:
        return [0, 1], float(D[0, 1] + D[1, 0])
    best_order, best_len = None, np.inf
    for perm in permutations(range(1, k)):
        order = (0, *perm)
        length = sum(D[order[i], order[i + 1]] for i in range(k - 1))
        length += D[order[-1], order[0]]
        if length < best_len:
            best_len, best_order = length, list(order)
    return best_order, float(best_len)


def tour_ascent(order: list[int], A: np.ndarray) -> float:
    """Ascent of the closed tour, walked in the cheaper direction."""
    k = len(order)
    fwd = sum(A[order[i], order[(i + 1) % k]] for i in range(k))
    rev = sum(A[order[(i + 1) % k], order[i]] for i in range(k))
    return float(min(fwd, rev))


def split_pair(members: list[int], D: np.ndarray) -> tuple[list[int], list[int]]:
    """Split a group in two, seeded by its farthest-apart pair."""
    sub = D[np.ix_(members, members)]
    i, j = np.unravel_index(np.argmax(sub), sub.shape)
    a, b = [], []
    for m_idx, m in enumerate(members):
        (a if sub[m_idx, i] <= sub[m_idx, j] else b).append(m)
    return a, b


def cluster_metrics(members: list[int], D: np.ndarray, A: np.ndarray):
    """(tour order, tour length m, tour ascent m) for one group."""
    if len(members) == 1:
        return list(members), 0.0, 0.0
    order_idx, length = tsp_tour(D[np.ix_(members, members)])
    if order_idx is None:
        return list(members), float("inf"), float("inf")
    ascent = tour_ascent(order_idx, A[np.ix_(members, members)])
    return [members[i] for i in order_idx], length, ascent


def build_clusters(numbers: list[int], dist: np.ndarray, ascent: np.ndarray,
                   trip: dict) -> list[dict]:
    n = len(numbers)
    max_tour_m = (trip["loop_km_max"] - trip["trailhead_reserve_km"]) * 1000
    min_tour_m = trip["loop_km_min"] * 1000
    max_size = trip["stamps_ideal_max"]

    D = np.minimum(dist, dist.T)  # walking is symmetric; keep the better pass
    if n > 1:
        capped = np.where(np.isfinite(D), D, UNREACH_M)
        Z = linkage(squareform(capped, checks=False), method="complete")
        labels = fcluster(Z, t=max_tour_m / 2, criterion="distance")
    else:
        labels = np.array([1])
    groups = [[i for i in range(n) if labels[i] == lab] for lab in sorted(set(labels))]

    final: list[list[int]] = []
    stack = groups
    while stack:
        g = stack.pop()
        if len(g) == 1:
            final.append(g)
            continue
        if len(g) > max_size:
            stack.extend(split_pair(g, D))
            continue
        _, length, asc = cluster_metrics(g, D, ascent)
        if length <= max_tour_m and asc <= trip["ascent_m_max"]:
            final.append(g)
        else:
            stack.extend(split_pair(g, D))

    def deficient(g: list[int]) -> bool:
        if len(g) < trip["stamps_ideal_min"]:
            return True
        _, length, _ = cluster_metrics(g, D, ascent)
        return length < min_tour_m

    while True:
        best = None
        for i in range(len(final)):
            for j in range(i + 1, len(final)):
                if not (deficient(final[i]) or deficient(final[j])):
                    continue
                gap = D[np.ix_(final[i], final[j])].min()
                if not np.isfinite(gap):
                    continue
                cand = final[i] + final[j]
                if len(cand) > max_size:
                    continue
                _, length, asc = cluster_metrics(cand, D, ascent)
                if length > max_tour_m or asc > trip["ascent_m_max"]:
                    continue
                if best is None or gap < best[0]:
                    best = (gap, i, j)
        if best is None:
            break
        _, i, j = best
        merged = final[i] + final[j]
        final = [g for k, g in enumerate(final) if k not in (i, j)]
        final.append(merged)

    out = []
    for g in sorted(final, key=lambda g: min(numbers[i] for i in g)):
        order, length, asc = cluster_metrics(g, D, ascent)
        out.append({
            "stamps": [numbers[i] for i in order],
            "est_loop_km": round(length / 1000, 2),
            "est_ascent_m": round(asc),
            "singleton": len(g) == 1,
        })
    return out


def main() -> None:
    cfg = config.load()
    if CLUSTERS_PATH.exists():
        print(f"{CLUSTERS_PATH} already exists — nothing to do")
        return
    m = np.load(MATRIX_PATH)
    numbers = m["numbers"].tolist()
    done = set(cfg["progress"]["done"])
    keep = [i for i, num in enumerate(numbers) if num not in done]
    clusters = build_clusters(
        [numbers[i] for i in keep],
        m["dist_m"][np.ix_(keep, keep)],
        m["ascent_m"][np.ix_(keep, keep)],
        cfg["trip"],
    )
    CLUSTERS_PATH.write_text(json.dumps(clusters, indent=2), encoding="utf-8")

    hikes = [c for c in clusters if not c["singleton"]]
    singles = [c["stamps"][0] for c in clusters if c["singleton"]]
    sizes = sorted(len(c["stamps"]) for c in hikes)
    kms = [c["est_loop_km"] for c in hikes]
    print(f"wrote {CLUSTERS_PATH}")
    print(f"{len(hikes)} multi-stamp trips covering {sum(sizes)} stamps, "
          f"{len(singles)} singletons: {singles}")
    print(f"trip sizes: min {sizes[0]}, max {sizes[-1]}; "
          f"est loop km: min {min(kms):.1f}, median {np.median(kms):.1f}, "
          f"max {max(kms):.1f}")


if __name__ == "__main__":
    main()
