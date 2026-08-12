"""Run the whole pipeline: `python -m harzplan` (or `... replan`).

Finished stages skip themselves via their cache files. `replan` drops the
planning caches (clusters, routes, ranking) so the remaining stamps are
regrouped — the expensive graph, matrix, parking, and drive caches stay.
"""
import sys

from . import acquire, cluster, network, outputs, rank, route
from .cluster import CLUSTERS_PATH
from .rank import RANKED_PATH
from .route import ROUTES_PATH

if len(sys.argv) > 1 and sys.argv[1] == "replan":
    for path in (CLUSTERS_PATH, ROUTES_PATH, RANKED_PATH):
        path.unlink(missing_ok=True)

for stage in (acquire, network, cluster, route, rank, outputs):
    print(f"=== {stage.__name__.rsplit('.', 1)[-1]} ===")
    stage.main()
