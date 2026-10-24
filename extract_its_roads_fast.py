
from pathlib import Path
import json
import time

import geopandas as gpd
import osmnx as ox
import folium
from pyrosm import OSM
from shapely.geometry import box, mapping, LineString, MultiLineString
from shapely.ops import transform
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "map_cache"
PBF = OUT / "northern-zone-latest.osm.pbf"
GRAPH = OUT / "its_10km_square.graphml"
BOUNDARY_FILE = OUT / "its_10km_square_boundary.geojson"
PREVIEW = OUT / "its_10km_square_preview.html"
META = OUT / "its_10km_square_metadata.json"

if not PBF.exists():
    raise SystemExit(f"Missing regional PBF: {PBF}")

# ITS Engineering College anchor; verify the pin against the actual entrance.
LAT, LON = 28.469195, 77.488792
CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32643"

fwd = Transformer.from_crs(CRS, METRIC_CRS, always_xy=True)
rev = Transformer.from_crs(METRIC_CRS, CRS, always_xy=True)

cx, cy = fwd.transform(LON, LAT)
square_utm = box(cx - 5000, cy - 5000, cx + 5000, cy + 5000)
square = transform(rev.transform, square_utm)
minx, miny, maxx, maxy = square.bounds

print("1/5 Reading regional PBF with Pyrosm...")
osm = OSM(
    str(PBF),
    bounding_box=[minx, miny, maxx, maxy],
)

print("2/5 Extracting drivable roads...")
result = osm.get_network(network_type="driving", nodes=True)

if not isinstance(result, tuple) or len(result) != 2:
    raise RuntimeError(
        "Unexpected Pyrosm result. Expected (nodes, edges); "
        f"received {type(result).__name__}."
    )

# Pyrosm returns (nodes, edges) when nodes=True.
nodes, edges = result

if nodes is None or nodes.empty:
    raise RuntimeError("Pyrosm returned no road nodes.")
if edges is None or edges.empty:
    raise RuntimeError("Pyrosm returned no driving-road edges.")

print(f"Road nodes extracted: {len(nodes):,}")
print(f"Road edges extracted: {len(edges):,}")

print("3/5 Preparing the routing graph and clipping preview roads...")

# Normalize nodes for OSMnx graph_from_gdfs().
nodes = nodes.copy()
edges = edges.copy()

if "id" not in nodes.columns:
    if nodes.index.name in ("id", "osmid"):
        nodes = nodes.reset_index()
    else:
        raise RuntimeError(
            f"Cannot identify node IDs. Node columns: {list(nodes.columns)}"
        )

if "id" not in nodes.columns:
    raise RuntimeError("Node ID column is missing.")

nodes = nodes.set_index("id", drop=True)
nodes.index.name = "osmid"

if "lon" in nodes.columns and "lat" in nodes.columns:
    nodes["x"] = nodes["lon"].astype(float)
    nodes["y"] = nodes["lat"].astype(float)
elif "geometry" in nodes.columns:
    nodes["x"] = nodes.geometry.x
    nodes["y"] = nodes.geometry.y
else:
    raise RuntimeError("Cannot determine node coordinates.")

nodes = gpd.GeoDataFrame(nodes, geometry="geometry", crs=CRS)

required = {"u", "v", "geometry"}
if not required.issubset(edges.columns):
    raise RuntimeError(
        f"Edge data is missing {required - set(edges.columns)}. "
        f"Edge columns: {list(edges.columns)}"
    )

edges = gpd.GeoDataFrame(edges, geometry="geometry", crs=CRS)

# OSMnx expects edges indexed by (u, v, key).
if "key" not in edges.columns:
    edges["key"] = edges.groupby(["u", "v"]).cumcount()

edges = edges.set_index(["u", "v", "key"], drop=True)
edges.index.names = ["u", "v", "key"]

# Supply metric edge lengths for routing costs.
edges_metric = edges.to_crs(METRIC_CRS)
edges["length"] = edges_metric.geometry.length.astype(float)

# Build graph using positional arguments for OSMnx compatibility.
print("4/5 Building routing graph...")
G = ox.graph_from_gdfs(nodes, edges)

if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
    raise RuntimeError("Routing graph is empty.")

# Save the graph and verify it can be reloaded.
ox.io.save_graphml(G, GRAPH)

BOUNDARY_FILE.write_text(
    json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "side_m": 10000,
                        "anchor_lat": LAT,
                        "anchor_lon": LON,
                    },
                    "geometry": mapping(square),
                }
            ],
        },
        indent=2,
    ),
    encoding="utf-8",
)

print("5/5 Saving offline preview and validating graph...")

m = folium.Map(
    location=[LAT, LON],
    zoom_start=13,
    tiles="OpenStreetMap",
    control_scale=True
)

folium.GeoJson(
    json.loads(BOUNDARY_FILE.read_text(encoding="utf-8")),
    style_function=lambda _: {
        "color": "#00a6c8",
        "weight": 3,
        "fillOpacity": 0,
    },
).add_to(m)

folium.Marker(
    [LAT, LON],
    tooltip="ITS anchor — verify exact entrance",
).add_to(m)

# Clip only the display layer to the exact 10 km x 10 km boundary.
roads_m = gpd.clip(edges.to_crs(METRIC_CRS), square_utm)
roads = roads_m.to_crs(CRS)
roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty]

print(f"Road geometries inside square: {len(roads):,}")

for geom in roads.geometry:
    if geom.geom_type == "LineString":
        lines = [geom]
    elif geom.geom_type == "MultiLineString":
        lines = list(geom.geoms)
    else:
        continue

    for line in lines:
        folium.PolyLine(
            [(lat, lon) for lon, lat in line.coords],
            color="#64748b",
            weight=1,
            opacity=0.7,
        ).add_to(m)

m.save(str(PREVIEW))

G2 = ox.io.load_graphml(GRAPH)
assert G2.number_of_nodes() == G.number_of_nodes()
assert G2.number_of_edges() == G.number_of_edges()

META.write_text(
    json.dumps(
        {
            "anchor": [LAT, LON],
            "square_side_m": 10000,
            "clipped_road_features": len(roads),
            "graph_nodes": G2.number_of_nodes(),
            "graph_edges": G2.number_of_edges(),
            "source_file": PBF.name,
            "graph_file": GRAPH.name,
            "boundary_file": BOUNDARY_FILE.name,
            "preview_file": PREVIEW.name,
            "validated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        indent=2,
    ),
    encoding="utf-8",
)

print("\nSUCCESS — local files saved and graph reload verified.")
for path in [GRAPH, BOUNDARY_FILE, PREVIEW, META]:
    print(f"{path.name}: {path.stat().st_size:,} bytes")
