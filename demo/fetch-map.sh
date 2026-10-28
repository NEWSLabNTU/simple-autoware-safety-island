#!/usr/bin/env bash
# Fetch Autoware's sample-map-planning (29 MB) into demo/map/ (gitignored).
#
# The map is not tracked here: it is the same bytes as the copy in
# NEWSLabNTU/autoware-safety-island (demo/map/sample-map-planning, added
# there by 6998300c), so it is pinned to that commit and checked by sha256.
# Idempotent: files already present with the right hash are kept.
#
#   demo/fetch-map.sh            # or: just demo-map
#   MAP_DIR=<dir> demo/fetch-map.sh
#
# Users: the legacy planning_simulator recipes (justfile _svc-sim),
# tools/timeline/run-native.sh, just/l3-demo.just (l3-container, the host
# run) and the L3 container build (COPY demo/map/sample-map-planning/).
set -euo pipefail
cd "$(dirname "$0")/.."

REPO=NEWSLabNTU/autoware-safety-island
REV=6998300c671bcd9e4af92241968120904192efcd
SRC=demo/map/sample-map-planning
DEST="${MAP_DIR:-demo/map/sample-map-planning}"
FILES=(
    "4fe358f2d1e182dc76de296e5619086f8d8ad2fcab3e6d8f99f6e3d724a84e6d  lanelet2_map.osm"
    "c7f8caeaad3559d2bc924a0683f36673f72c9e15f315c2e95f371c9ccceb7e39  map_config.yaml"
    "9753eba4724aa6d41ffa2cc03e8da2d82e9f317dd14da837b0e96a7705e72bfa  map_projector_info.yaml"
    "2da791365627241513c56a88a78baaf17d86b5e90febcb8987ec92c9e99ad2c6  pointcloud_map.pcd"
)

mkdir -p "$DEST"
for line in "${FILES[@]}"; do
    sum="${line%%  *}" name="${line#*  }"
    f="$DEST/$name"
    if [ -f "$f" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sum" ]; then
        continue
    fi
    url="https://raw.githubusercontent.com/$REPO/$REV/$SRC/$name"
    echo "fetch-map: $name <- $REPO@${REV:0:12}"
    curl -fsSL --retry 3 -o "$f.part" "$url"
    got="$(sha256sum "$f.part" | cut -d' ' -f1)"
    if [ "$got" != "$sum" ]; then
        rm -f "$f.part"
        echo "fetch-map: $name sha256 $got, expected $sum" >&2
        exit 1
    fi
    mv "$f.part" "$f"
done
echo "fetch-map: $DEST OK (${#FILES[@]} files, $REPO@${REV:0:12})"
