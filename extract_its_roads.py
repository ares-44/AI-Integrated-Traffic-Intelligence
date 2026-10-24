from pathlib import Path
import json, math, time
import osmium
import networkx as nx
import folium
from shapely.geometry import box, LineString, mapping
from shapely.ops import transform
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "map_cache"
PBF = OUT / "northern-zone-latest.osm.pbf"
GRAPH = OUT / "its_10km_square.graphml"
BOUNDARY = OUT / "its_10km_square_boundary.geojson"
PREVIEW = OUT / "its_10km_square_preview.html"
META = OUT / "its_10km_square_metadata.json"

if not PBF.exists() or PBF.stat().st_size < 10_000_000:
    raise SystemExit(f"Regional PBF missing or suspiciously small: {PBF}")

# Anchor coordinate selected for ITS Engineering College.
LAT, LON = 28.469195, 77.488792
fwd = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
rev = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)
cx, cy = fwd.transform(LON, LAT)
square_m = box(cx - 5000, cy - 5000, cx + 5000, cy + 5000)
square = transform(rev.transform, square_m)
west, south, east, north = square.bounds

print("1/5 Local PBF extraction; no Overpass requests.")
print(f"Input: {PBF} ({PBF.stat().st_size / 1e6:.1f} MB)")
print("2/5 Reading highway ways and clipping segments...")

G = nx.MultiDiGraph()
coord_to_id = {}
next_id = 1
ways_seen = 0
segments_kept = 0

def node_id(lon, lat):
    global next_id
    key = (round(lon, 7), round(lat, 7))
    if key not in coord_to_id:
        coord_to_id[key] = next_id
        G.add_node(next_id, x=float(lon), y=float(lat))
        next_id += 1
    return coord_to_id[key]

class RoadHandler(osmium.SimpleHandler):
    def way(self, w):
        global ways_seen, segments_kept
        tags = {t.k: t.v for t in w.tags}
        highway = tags.get("highway")
        if not highway or highway in {
            "footway", "path", "steps", "cycleway", "bridleway",
            "pedestrian", "construction", "proposed", "raceway"
        }:
            return

        coords = []
        for n in w.nodes:
            if not n.location.valid():
                return
            coords.append((n.location.lon, n.location.lat))
        if len(coords) < 2:
            return

        ways_seen += 1
        oneway = tags.get("oneway", "").lower()
        reverse_only = oneway == "-1"
        is_oneway = oneway in ("yes", "1", "true", "-1") or (
            highway in ("motorway", "motorway_link") or tags.get("junction") == "roundabout"
        )
        speed = 40.0
        try:
            maxspeed = tags.get("maxspeed", "").split()[0]
            speed = float(maxspeed)
            if speed > 130:
                speed /= 1.60934
        except (ValueError, IndexError):
            pass

        for a, b in zip(coords[:-1], coords[1:]):
            try:
                clipped = LineString([a, b]).intersection(square)
            except Exception:
                continue
            if clipped.is_empty:
                continue
            lines = [clipped] if clipped.geom_type == "LineString" else [
                g for g in getattr(clipped, "geoms", []) if g.geom_type == "LineString"
            ]
            for line in lines:
                pts = list(line.coords)
                for p, q in zip(pts[:-1], pts[1:]):
                    lon1, lat1 = p
                    lon2, lat2 = q
                    if math.hypot(lon2 - lon1, lat2 - lat1) < 1e-10:
                        continue
                    x1, y1 = fwd.transform(lon1, lat1)
                    x2, y2 = fwd.transform(lon2, lat2)
                    length = math.hypot(x2 - x1, y2 - y1)
                    if length <= 0:
                        continue
                    u, v = node_id(lon1, lat1), node_id(lon2, lat2)
                    attrs = {
                        "length": float(length),
                        "highway": str(highway),
                        "name": str(tags.get("name", "")),
                        "maxspeed_kph": float(speed),
                        "osmid": str(w.id),
                    }
                    if reverse_only:
                        G.add_edge(v, u, **attrs)
                    else:
                        G.add_edge(u, v, **attrs)
                    if not is_oneway:
                        G.add_edge(v, u, **attrs)
                    segments_kept += 1

handler = RoadHandler()
handler.apply_file(str(PBF), locations=True, idx="flex_mem")

if G.number_of_nodes() < 2 or G.number_of_edges() < 1:
    raise RuntimeError("No road segments extracted inside the square. Do not use an empty graph.")

print(f"Ways scanned: {ways_seen:,}; clipped segments: {segments_kept:,}")
print(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} directed edges")

print("3/5 Saving graph, boundary and scenario maths...")
nx.set_graph_attributes(G, {
    "crs": "EPSG:4326",
    "source": "OpenStreetMap regional PBF extract",
    "anchor_lat": LAT,
    "anchor_lon": LON,
    "square_side_m": 10000
})
nx.write_graphml(G, GRAPH)

BOUNDARY.write_text(json.dumps({
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"side_m": 10000, "anchor_lat": LAT, "anchor_lon": LON},
        "geometry": mapping(square)
    }]
}, indent=2), encoding="utf-8")

(OUT / "scenario_math_config.json").write_text(json.dumps({
    "crowd_density": "D = N / A people/m^2",
    "congestion": "C = clamp(1 - v/v_ref, 0, 1)",
    "density_normalization": "D_n = clamp(D/4, 0, 1)",
    "zone_risk": "R = 0.5*D_n + 0.3*T_n + 0.2*F_n",
    "route_cost": "J(P) = sum(L_km * (1 + 2*C + 3*R))",
    "note": "Weights and simulated traffic/risk require local validation; not live traffic."
}, indent=2), encoding="utf-8")

print("4/5 Building offline vector preview...")
m = folium.Map(location=[LAT, LON], zoom_start=12, tiles=None)
folium.GeoJson(
    json.loads(BOUNDARY.read_text(encoding="utf-8")),
    style_function=lambda _: {"color": "#00a6c8", "weight": 3, "fillOpacity": 0}
).add_to(m)
folium.Marker([LAT, LON], tooltip="ITS study anchor — verify exact campus entrance").add_to(m)
for u, v, data in G.edges(data=True):
    folium.PolyLine(
        [(G.nodes[u]["y"], G.nodes[u]["x"]),
         (G.nodes[v]["y"], G.nodes[v]["x"])],
        color="#64748b", weight=1, opacity=0.65
    ).add_to(m)
m.save(str(PREVIEW))

print("5/5 Reload validation...")
G2 = nx.read_graphml(GRAPH)
assert len(G2.nodes) == G.number_of_nodes()
assert len(G2.edges) == G.number_of_edges()
assert all("x" in d and "y" in d for _, d in G2.nodes(data=True))

META.write_text(json.dumps({
    "anchor": [LAT, LON],
    "square_side_m": 10000,
    "nodes": len(G2.nodes),
    "directed_edges": len(G2.edges),
    "ways_scanned": ways_seen,
    "segments_kept": segments_kept,
    "source_file": PBF.name,
    "graph_file": GRAPH.name,
    "boundary_file": BOUNDARY.name,
    "preview_file": PREVIEW.name,
    "validated_at": time.strftime("%Y-%m-%d %H:%M:%S")
}, indent=2), encoding="utf-8")

print("\nSUCCESS: local road graph saved and reopened successfully.")
for f in (GRAPH, BOUNDARY, PREVIEW, META, OUT / "scenario_math_config.json"):
    print(f"{f.name}: {f.stat().st_size:,} bytes")
