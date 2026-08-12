"""Step 2: walking network, elevation, and the 222x222 stamp distance matrix.

Sub-stages, each cached under cache/ so a crash never repeats finished work:
  1. graph.pkl       raw OSMnx walking graph for the Harz bounding box
  2. graph_elev.pkl  same graph with a DEM elevation per node
  3. stamp_matrix.npz  pairwise network distance + ascent between all stamps
"""
import json
import math
import pickle
import urllib.request
from pathlib import Path

import numpy as np

from . import config

MATRIX_PATH = config.ROOT / "cache" / "stamp_matrix.npz"


def load_stamps() -> list[dict]:
    with open(config.ROOT / "data" / "stamps.geojson", encoding="utf-8") as f:
        gj = json.load(f)
    return [
        {
            "number": ft["properties"]["number"],
            "name": ft["properties"]["name"],
            "lon": ft["geometry"]["coordinates"][0],
            "lat": ft["geometry"]["coordinates"][1],
        }
        for ft in gj["features"]
    ]


def compute_bbox(lats: list[float], lons: list[float], buffer_km: float) -> tuple:
    """(west, south, east, north) around all points, plus a buffer."""
    mid_lat = (min(lats) + max(lats)) / 2
    dlat = buffer_km / 110.574
    dlon = buffer_km / (111.320 * math.cos(math.radians(mid_lat)))
    return (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)


def dem_tile_names(bbox: tuple) -> list[str]:
    """1-degree Copernicus tile names covering the bbox (Harz is all N/E)."""
    west, south, east, north = bbox
    return [
        f"N{lat:02d}_00_E{lon:03d}_00"
        for lat in range(math.floor(south), math.floor(north) + 1)
        for lon in range(math.floor(west), math.floor(east) + 1)
    ]


def fetch_dem(bbox: tuple, url_template: str, dem_dir: Path) -> list[Path]:
    paths = []
    for tile in dem_tile_names(bbox):
        dest = dem_dir / f"{tile}.tif"
        if not dest.exists():
            url = url_template.format(tile=tile)
            print(f"downloading DEM tile {tile} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=300).read()
            dem_dir.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        paths.append(dest)
    return paths


def build_graph(bbox: tuple, cfg: dict):
    import osmnx as ox
    import requests

    ox.settings.cache_folder = str(config.ROOT / "cache" / "osmnx")
    ox.settings.max_query_area_size = cfg["overpass_query_km2"] * 1e6
    ox.settings.requests_timeout = cfg["overpass_timeout_s"]
    last_error = None
    for url in cfg["overpass_urls"]:
        ox.settings.overpass_url = url
        ox.settings.overpass_rate_limit = "overpass-api.de" in url
        print(f"downloading walking network via {url}, bbox {bbox} ...")
        try:
            return ox.graph_from_bbox(bbox, network_type="walk", simplify=True)
        except requests.RequestException as err:
            print(f"endpoint failed ({err}); trying next")
            last_error = err
    raise last_error


def add_elevations(G, dem_paths: list[Path]) -> None:
    import rasterio
    from rasterio.transform import rowcol

    nodes = list(G.nodes)
    xs = np.array([G.nodes[n]["x"] for n in nodes])
    ys = np.array([G.nodes[n]["y"] for n in nodes])
    elev = np.full(len(nodes), np.nan)
    for path in dem_paths:
        with rasterio.open(path) as ds:
            left, bottom, right, top = ds.bounds
            inside = (xs >= left) & (xs < right) & (ys > bottom) & (ys <= top)
            if not inside.any():
                continue
            band = ds.read(1)
            rows, cols = rowcol(ds.transform, xs[inside], ys[inside])
            rows = np.clip(rows, 0, band.shape[0] - 1)
            cols = np.clip(cols, 0, band.shape[1] - 1)
            elev[inside] = band[rows, cols]
    if np.isnan(elev).any():
        raise RuntimeError(f"{int(np.isnan(elev).sum())} nodes outside all DEM tiles")
    for n, e in zip(nodes, elev):
        G.nodes[n]["elevation"] = float(e)


def nearest_graph_nodes(G, lonlats: list[tuple]) -> list[tuple]:
    """For each (lon, lat) return (nearest graph node, distance in metres)."""
    from scipy.spatial import cKDTree

    nodes = list(G.nodes)
    xs = np.array([G.nodes[n]["x"] for n in nodes])
    ys = np.array([G.nodes[n]["y"] for n in nodes])
    mx = 111_320 * math.cos(math.radians(float(ys.mean())))
    my = 110_574
    tree = cKDTree(np.c_[xs * mx, ys * my])
    out = []
    for lon, lat in lonlats:
        d, i = tree.query([lon * mx, lat * my])
        out.append((nodes[int(i)], float(d)))
    return out


def snap_stamps(G, stamps: list[dict]) -> dict[int, tuple]:
    """Map stamp number -> (nearest graph node, snap distance in metres)."""
    hits = nearest_graph_nodes(G, [(s["lon"], s["lat"]) for s in stamps])
    return {s["number"]: hit for s, hit in zip(stamps, hits)}


def build_csr(G):
    """Graph as a CSR adjacency matrix for C-speed Dijkstra.

    Returns (A, nodes, idx, elev): parallel edges collapse to their minimum
    length, node order in `nodes` matches CSR indices and `elev`.
    """
    from scipy.sparse import csr_matrix

    nodes = list(G.nodes)
    idx = {n: i for i, n in enumerate(nodes)}
    elev = np.array([G.nodes[n].get("elevation", 0.0) for n in nodes])
    best: dict[tuple, float] = {}
    for u, v, data in G.edges(data=True):
        key = (idx[u], idx[v])
        length = data["length"]
        if key not in best or length < best[key]:
            best[key] = length
    rows = np.array([k[0] for k in best], dtype=np.int64)
    cols = np.array([k[1] for k in best], dtype=np.int64)
    vals = np.array(list(best.values()))
    A = csr_matrix((vals, (rows, cols)), shape=(len(nodes), len(nodes)))
    return A, nodes, idx, elev


def walk_path(pred: np.ndarray, si: int, ti: int) -> list[int]:
    """Node index path source -> target from a Dijkstra predecessor array."""
    path = [ti]
    while path[-1] != si:
        path.append(int(pred[path[-1]]))
    path.reverse()
    return path


def pairwise(A, elev: np.ndarray, src_idx: list[int], limit_m: float,
             want_pred: bool = False):
    """Distance (m) and path ascent (m, directional) between the given nodes.

    One Dijkstra per source; ascent is summed from node elevations along
    each predecessor path. Optionally keeps the predecessor arrays for
    later geometry extraction.
    """
    from scipy.sparse.csgraph import dijkstra

    k = len(src_idx)
    dist = np.full((k, k), np.inf)
    ascent = np.full((k, k), np.inf)
    preds = []
    for a, si in enumerate(src_idx):
        d, pred = dijkstra(A, indices=si, return_predecessors=True, limit=limit_m)
        if want_pred:
            preds.append(pred)
        dist[a, a] = ascent[a, a] = 0.0
        for b, ti in enumerate(src_idx):
            if b == a or not np.isfinite(d[ti]):
                continue
            dist[a, b] = d[ti]
            path = walk_path(pred, si, ti)
            gain = elev[path[1:]] - elev[path[:-1]]
            ascent[a, b] = float(np.maximum(gain, 0.0).sum())
    return dist, ascent, preds if want_pred else None


def stamp_matrices(G, node_by_number: dict, limit_m: float):
    """Network distance and ascent between all stamps, by stamp number."""
    A, nodes, idx, elev = build_csr(G)
    numbers = sorted(node_by_number)
    src = [idx[node_by_number[m]] for m in numbers]
    dist, ascent, _ = pairwise(A, elev, src, limit_m)
    return numbers, dist, ascent


def ensure_graph(cfg: dict, bbox: tuple):
    cache = config.ROOT / "cache"
    elev_pkl = cache / "graph_elev.pkl"
    if elev_pkl.exists():
        print("loading cached graph with elevations ...")
        with open(elev_pkl, "rb") as f:
            return pickle.load(f)
    raw_pkl = cache / "graph.pkl"
    if raw_pkl.exists():
        print("loading cached raw graph ...")
        with open(raw_pkl, "rb") as f:
            G = pickle.load(f)
    else:
        G = build_graph(bbox, cfg)
        cache.mkdir(parents=True, exist_ok=True)
        with open(raw_pkl, "wb") as f:
            pickle.dump(G, f, protocol=5)
        print(f"graph cached: {len(G.nodes)} nodes, {len(G.edges)} edges")
    dem_paths = fetch_dem(bbox, cfg["dem_url_template"], cache / "dem")
    add_elevations(G, dem_paths)
    with open(elev_pkl, "wb") as f:
        pickle.dump(G, f, protocol=5)
    raw_pkl.unlink()
    return G


def main() -> None:
    cfg = config.load()["network"]
    stamps = load_stamps()
    if MATRIX_PATH.exists():
        m = np.load(MATRIX_PATH)
        print(f"matrix already built for {len(m['numbers'])} stamps — nothing to do")
        return
    bbox = compute_bbox(
        [s["lat"] for s in stamps], [s["lon"] for s in stamps], cfg["bbox_buffer_km"]
    )
    G = ensure_graph(cfg, bbox)
    print(f"graph: {len(G.nodes)} nodes, {len(G.edges)} edges")

    snapped = snap_stamps(G, stamps)
    for s in stamps:
        node, d = snapped[s["number"]]
        if d > cfg["snap_warn_m"]:
            print(f"WARNING stamp {s['number']} {s['name']}: snap {d:.0f} m")

    print("running 222 Dijkstra passes ...")
    node_by_number = {n: node for n, (node, _) in snapped.items()}
    numbers, dist, ascent = stamp_matrices(
        G, node_by_number, cfg["pair_dist_limit_km"] * 1000
    )
    np.savez_compressed(
        MATRIX_PATH,
        numbers=np.array(numbers),
        dist_m=dist,
        ascent_m=ascent,
        snap_m=np.array([snapped[n][1] for n in numbers]),
        node_ids=np.array([node_by_number[n] for n in numbers], dtype=np.int64),
    )
    finite = np.isfinite(dist) & (dist > 0)
    nearest = np.where(finite, dist, np.inf).min(axis=1)
    print(f"wrote {MATRIX_PATH}")
    print(f"nearest-stamp distance: median {np.median(nearest)/1000:.1f} km, "
          f"max {nearest.max()/1000:.1f} km")


if __name__ == "__main__":
    main()
