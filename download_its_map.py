from pathlib import Path
import json
import math
import time
import osmnx as ox
import folium
from shapely.geometry import box, mapping
from shapely.ops import transform
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "map_cache"
OUT.mkdir(parents=True, exist_ok=True)

GRAPH = OUT / "its_10km_square.graphml"
BOUNDARY = OUT / "its_10km_square_boundary.geojson"
PREVIEW = OUT / "its_10km_square_preview.html"
META = OUT / "its_10km_square_metadata.json"
MATH = OUT / "scenario_math_config.json"

# Published coordinate previously selected for the college.
# Verify this pin against the actual campus entrance before final use.
LAT, LON = 28.469195, 77.488792

print("1/6 Constructing exact 10 km x 10 km square...")
forward = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
reverse = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
x, y = forward.transform(LON, LAT)
square_m = box(x - 5000, y - 5000, x + 5000, y + 5000)
square_ll = transform(reverse.transform, square_m)

print("2/6 Downloading driving road network from OpenStreetMap...")
# Rotate public Overpass endpoints when one resets the connection.
ox.settings.overpass_url = "https://overpass.kumi.systems/api"
ox.settings.requests_timeout = 240
ox.settings.overpass_rate_limit = True

ox.settings.requests_timeout = 180
G = ox.graph.graph_from_polygon(
    square_ll,
    network_type="drive",
    simplify=True,
    retain_all=True,
    truncate_by_edge=True
)

if G.number_of_nodes() < 2 or G.number_of_edges() < 1:
    raise RuntimeError("Road download returned an empty or invalid network.")

print(f"Downloaded nodes: {G.number_of_nodes():,}")
print(f"Downloaded directed road edges: {G.number_of_edges():,}")

print("3/6 Saving graph and geographic boundary...")
ox.io.save_graphml(G, GRAPH)

BOUNDARY.write_text(json.dumps({
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "name": "ITS study area",
            "width_m": 10000,
            "height_m": 10000,
            "anchor_lat": LAT,
            "anchor_lon": LON,
            "source": "OpenStreetMap"
        },
        "geometry": mapping(square_ll)
    }]
}, indent=2), encoding="utf-8")

print("4/6 Saving mathematical scenario configuration...")
MATH.write_text(json.dumps({
    "units": {
        "distance": "km",
        "crowd_density": "people/m^2",
        "congestion": "dimensionless 0..1",
        "risk": "dimensionless 0..1"
    },
    "crowd_density": "D = N / A",
    "congestion": "C = clamp(1 - v / v_ref, 0, 1)",
    "zone_risk": "R = 0.5*D_n + 0.3*T_n + 0.2*F_n",
    "density_normalization": "D_n = clamp(D / 4, 0, 1)",
    "traffic_normalization": "T_n = clamp(C, 0, 1)",
    "flow_normalization": "F_n = clamp(flow_score, 0, 1)",
    "safe_route_cost": "J(P) = sum(alpha*L_e + beta*C_e + gamma*R_e)",
    "example_weights": {"alpha": 1.0, "beta": 2.0, "gamma": 3.0},
    "weight_note": "Illustrative weights; calibrate using validated local observations.",
    "data_note": "Roads from OpenStreetMap; scenario congestion and risk are simulated unless measured data is connected."
}, indent=2), encoding="utf-8")

print("5/6 Building an offline road-map preview...")
m = folium.Map(location=[LAT, LON], zoom_start=12, tiles=None)
folium.GeoJson(
    json.loads(BOUNDARY.read_text(encoding="utf-8")),
    name="10 km square",
    style_function=lambda _: {
        "color": "#00a6c8", "weight": 3, "fillOpacity": 0
    }
).add_to(m)
folium.Marker(
    [LAT, LON],
    tooltip="ITS anchor — verify exact campus entrance"
).add_to(m)

for u, v, data in G.edges(data=True):
    try:
        geom = data.get("geometry")
        if geom is not None:
            coords = [(b, a) for a, b in geom.coords]
        else:
            coords = [
                (G.nodes[u]["y"], G.nodes[u]["x"]),
                (G.nodes[v]["y"], G.nodes[v]["x"])
            ]
        folium.PolyLine(
            coords, color="#667788", weight=1, opacity=0.8
        ).add_to(m)
    except (KeyError, TypeError, ValueError):
        continue

m.save(str(PREVIEW))

print("6/6 Verifying the saved graph...")
G2 = ox.io.load_graphml(GRAPH)
assert G2.number_of_nodes() == G.number_of_nodes()
assert G2.number_of_edges() == G.number_of_edges()

META.write_text(json.dumps({
    "anchor_lat": LAT,
    "anchor_lon": LON,
    "square_side_m": 10000,
    "graph_nodes": G2.number_of_nodes(),
    "graph_edges": G2.number_of_edges(),
    "graph_file": GRAPH.name,
    "boundary_file": BOUNDARY.name,
    "preview_file": PREVIEW.name,
    "math_config_file": MATH.name,
    "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S")
}, indent=2), encoding="utf-8")

print("\nSUCCESS: download, save, and reload validation passed.")
print(f"Output folder: {OUT}")
for p in [GRAPH, BOUNDARY, PREVIEW, META, MATH]:
    print(f"{p.name}: {p.stat().st_size:,} bytes")
