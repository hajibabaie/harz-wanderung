"""Step 4: give every cluster a parking trailhead and a real walking loop.

For each cluster: collect nearby OSM parking spots, compute network
distances between them and the cluster's stamps, pick the parking that
gives the shortest closed loop, and extract the loop's path geometry
for GPX export. Loops walk in the direction with less climbing.
"""
import json
import math
import pickle

import numpy as np

from . import config
from .cluster import CLUSTERS_PATH, tsp_tour
from .network import (
    build_csr,
    compute_bbox,
    load_stamps,
    MATRIX_PATH,
    nearest_graph_nodes,
    pairwise,
    walk_path,
)

ROUTES_PATH = config.ROOT / "cache" / "routes.json"
PARKING_PATH = config.ROOT / "cache" / "parking.json"


def orient_loop(order: list[int], A: np.ndarray) -> tuple[list[int], float]:
    """Walk the closed tour in whichever direction climbs less."""
    k = len(order)
    fwd = sum(A[order[i], order[(i + 1) % k]] for i in range(k))
    rev = sum(A[order[(i + 1) % k], order[i]] for i in range(k))
    if rev < fwd:
        return [order[0], *order[1:][::-1]], float(rev)
    return list(order), float(fwd)


def best_trailhead(D: np.ndarray, A: np.ndarray, n_cand: int):
    """Shortest closed loop over one candidate trailhead plus all stamps.

    D and A cover [candidate 0..n_cand-1, stamp 0..k-1]. Returns
    (candidate index, oriented order in D indices, loop metres, ascent metres)
    or None when no candidate reaches every stamp.
    """
    stamp_sel = list(range(n_cand, D.shape[0]))
    best = None
    for c in range(n_cand):
        sel = [c, *stamp_sel]
        sub = D[np.ix_(sel, sel)]
        if not np.isfinite(sub).all():
            continue
        order_idx, length = tsp_tour(sub)
        if best is None or length < best[2]:
            best = (c, [sel[i] for i in order_idx], length)
    if best is None:
        return None
    c, order, length = best
    order, ascent = orient_loop(order, A)
    return c, order, float(length), ascent


def loop_geometry(order: list[int], src_idx: list[int], preds: list,
                  nodes: list, G) -> list[tuple]:
    """(lat, lon) polyline of the closed loop, following network paths."""
    coords = []
    for i in range(len(order)):
        a, b = order[i], order[(i + 1) % len(order)]
        path = walk_path(preds[a], src_idx[a], src_idx[b])
        seg = [(G.nodes[nodes[p]]["y"], G.nodes[nodes[p]]["x"]) for p in path]
        coords.extend(seg[1:] if coords else seg)
    return coords


def fetch_parking(bbox: tuple, net_cfg: dict) -> list[dict]:
    """All public OSM parking spots in the Harz bbox, cached to disk."""
    if PARKING_PATH.exists():
        return json.loads(PARKING_PATH.read_text(encoding="utf-8"))
    import osmnx as ox

    ox.settings.cache_folder = str(config.ROOT / "cache" / "osmnx")
    ox.settings.max_query_area_size = net_cfg["overpass_query_km2"] * 1e6
    ox.settings.requests_timeout = net_cfg["overpass_timeout_s"]
    print("downloading OSM parking spots ...")
    gdf = ox.features.features_from_bbox(bbox, {"amenity": "parking"})
    out = []
    for _, row in gdf.iterrows():
        access = row.get("access")
        if isinstance(access, str) and access in ("private", "no"):
            continue
        geom = row.geometry
        point = geom if geom.geom_type == "Point" else geom.representative_point()
        name = row.get("name")
        out.append({
            "lat": float(point.y),
            "lon": float(point.x),
            "name": name if isinstance(name, str) and name else "Parkplatz",
        })
    PARKING_PATH.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def candidate_parkings(parking: list[dict], stamp_pts: list[tuple],
                       radius_km: float, max_candidates: int) -> list[int]:
    """Indices of parkings near any stamp; nearest overall as fallback."""
    from scipy.spatial import cKDTree

    lat0 = sum(lat for _, lat in stamp_pts) / len(stamp_pts)
    mx = 111_320 * math.cos(math.radians(lat0))
    my = 110_574
    ppts = np.array([[p["lon"] * mx, p["lat"] * my] for p in parking])
    tree = cKDTree(ppts)
    spts = np.array([[lon * mx, lat * my] for lon, lat in stamp_pts])
    dists = np.full(len(parking), np.inf)
    for s in spts:
        d, i = tree.query(s, k=min(len(parking), max_candidates * 4))
        d, i = np.atleast_1d(d), np.atleast_1d(i)
        np.minimum.at(dists, i, d)
    near = np.where(dists <= radius_km * 1000)[0]
    if len(near) == 0:
        near = np.array([int(np.argmin(dists))])
    return near[np.argsort(dists[near])][:max_candidates].tolist()


def main() -> None:
    cfg = config.load()
    trip, net_cfg, route_cfg = cfg["trip"], cfg["network"], cfg["route"]
    if ROUTES_PATH.exists():
        print(f"{ROUTES_PATH} already exists — nothing to do")
        return
    clusters = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
    stamps = {s["number"]: s for s in load_stamps()}
    print("loading graph ...")
    with open(config.ROOT / "cache" / "graph_elev.pkl", "rb") as f:
        G = pickle.load(f)
    A, nodes, idx, elev = build_csr(G)
    m = np.load(MATRIX_PATH)
    stamp_node = dict(zip(m["numbers"].tolist(), m["node_ids"].tolist()))
    bbox = compute_bbox(
        [s["lat"] for s in stamps.values()],
        [s["lon"] for s in stamps.values()],
        net_cfg["bbox_buffer_km"],
    )
    parking = fetch_parking(bbox, net_cfg)
    print(f"{len(parking)} public parking spots available")

    routes = []
    limit_m = trip["loop_km_max"] * 1000
    for ci, c in enumerate(clusters):
        nums = c["stamps"]
        stamp_pts = [(stamps[n]["lon"], stamps[n]["lat"]) for n in nums]
        cand_ids = candidate_parkings(
            parking, stamp_pts,
            route_cfg["parking_radius_km"], route_cfg["max_parking_candidates"],
        )
        cand_nodes = nearest_graph_nodes(
            G, [(parking[i]["lon"], parking[i]["lat"]) for i in cand_ids]
        )
        src_nodes = [n for n, _ in cand_nodes] + [stamp_node[n] for n in nums]
        src_idx = [idx[n] for n in src_nodes]
        D, Asc, preds = pairwise(A, elev, src_idx, limit_m, want_pred=True)
        found = best_trailhead(D, Asc, len(cand_ids))
        entry = {"stamps": nums, "singleton": c["singleton"]}
        if found is None:
            entry["unroutable"] = True
            print(f"WARNING cluster {nums}: no parking reaches every stamp")
        else:
            cand, order, loop_m, ascent_m = found
            p = parking[cand_ids[cand]]
            n_cand = len(cand_ids)
            entry.update({
                "stamps": [nums[i - n_cand] for i in order if i >= n_cand],
                "trailhead": p,
                "loop_km": round(loop_m / 1000, 2),
                "ascent_m": round(ascent_m),
                "geometry": loop_geometry(order, src_idx, preds, nodes, G),
                "over_limit": bool(loop_m > limit_m),
            })
        routes.append(entry)
        if (ci + 1) % 10 == 0:
            print(f"routed {ci + 1}/{len(clusters)} clusters")

    ROUTES_PATH.write_text(json.dumps(routes, ensure_ascii=False), encoding="utf-8")
    ok = [r for r in routes if "loop_km" in r]
    over = [r for r in ok if r["over_limit"]]
    print(f"wrote {ROUTES_PATH}")
    print(f"{len(ok)} routed trips, {len(over)} over the loop limit, "
          f"{len(routes) - len(ok)} unroutable")


if __name__ == "__main__":
    main()
