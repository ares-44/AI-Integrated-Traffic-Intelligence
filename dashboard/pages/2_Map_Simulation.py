
import math
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="PS06 Traffic & Crowd Command Centre",
    layout="wide",
)

st.title("PS06 | Integrated Traffic & Crowd Command Centre")
st.caption(
    "OpenStreetMap • Road-following routes • R-risk scoring "
    "• Crowd hotspots • Emergency corridor simulation"
)

# Approximate campus/landmark coordinates for Greater Noida.
# Verify each pin before using it for real-world dispatch.
PLACES = {
    "ITS Engineering College": (28.469195, 77.488792),
    "Dronacharya Group of Institutions": (28.4755, 77.4845),
    "KCC Institute of Technology & Management": (28.4770, 77.4905),
    "Accurate Institute of Management & Technology": (28.4730, 77.4960),
    "Amity University Greater Noida": (28.4725, 77.4825),
    "Sharda University": (28.4744, 77.4830),
    "GL Bajaj Institute": (28.4750, 77.4920),
    "Greater Noida Institute of Technology (GNIOT)": (28.4770, 77.4935),
    "NIMT Greater Noida": (28.4565, 77.5010),
    "Knowledge Park II Metro": (28.4600, 77.5000),
    "Knowledge Park III": (28.4785, 77.4814),
    "Pari Chowk": (28.4670, 77.5130),
    "India Expo Centre": (28.4525, 77.5005),
}

SCENARIO_FACTOR = {
    "Normal traffic": 0.25,
    "College rush": 0.65,
    "Metro passenger surge": 0.70,
    "Festival / mass gathering": 0.85,
    "Road blockage / accident": 0.80,
    "Emergency response": 0.55,
}

COLLEGE_NAMES = [
    name for name in PLACES
    if name not in {
        "Knowledge Park II Metro",
        "Knowledge Park III",
        "Pari Chowk",
        "India Expo Centre",
    }
]


def clamp(value, low=0.0, high=1.0):
    return min(high, max(low, value))


@st.cache_data(ttl=60, show_spinner=False)
def get_routes(origin, destination):
    """Get real road-following geometry from the public OSRM router."""
    coordinates = (
        f"{origin[1]},{origin[0]};"
        f"{destination[1]},{destination[0]}"
    )
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{coordinates}"
    )

    response = requests.get(
        url,
        params={
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "3",
            "steps": "true",
        },
        timeout=15,
        headers={"User-Agent": "PS06-Traffic-Crowd-Simulator/1.0"},
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "Ok":
        return []

    return data.get("routes", [])


def risk_for_place(
    is_hotspot,
    density_norm,
    traffic_norm,
    flow_norm,
    demand_norm,
):
    """
    Transparent illustrative risk score in [0, 1].
    Without live sensor feeds, this is a scenario estimate, not
    a measured real-world traffic risk.
    """
    local_density = density_norm if is_hotspot else 0.0
    local_flow = flow_norm if is_hotspot else 0.5 * flow_norm

    return clamp(
        0.5 * local_density
        + 0.3 * max(traffic_norm, demand_norm)
        + 0.2 * local_flow
    )


# ---------------- Sidebar controls ----------------
with st.sidebar:
    st.header("Scenario configuration")

    scenario = st.selectbox("Scenario", list(SCENARIO_FACTOR))

    journey_options = list(PLACES)
    origin_name = st.selectbox(
        "Journey start",
        journey_options,
        index=0,
    )
    destination_name = st.selectbox(
        "Final destination",
        journey_options,
        index=journey_options.index("Pari Chowk"),
    )
    crowd_name = st.selectbox(
        "Crowd hotspot",
        journey_options,
        index=journey_options.index("Knowledge Park III"),
    )

    crowd_count = st.number_input(
        "Estimated people at hotspot",
        min_value=0,
        max_value=200000,
        value=1200,
        step=100,
    )
    usable_area = st.number_input(
        "Usable crowd area (m²)",
        min_value=1.0,
        max_value=1000000.0,
        value=600.0,
        step=50.0,
    )
    traffic_demand = st.slider("Traffic demand (%)", 0, 100, 45)
    crowd_flow = st.slider("Crowd-flow / bottleneck (%)", 0, 100, 35)
    reference_speed = st.slider(
        "Reference free-flow speed (km/h)", 10, 80, 40
    )
    measured_speed = st.slider(
        "Scenario average speed (km/h)", 0, 80, 25
    )

    block_road = st.checkbox(
        "Simulate road closure",
        value=(scenario == "Road blockage / accident"),
    )
    emergency_priority = st.checkbox(
        "Highlight emergency corridor",
        value=(scenario == "Emergency response"),
    )

    show_all_places = st.checkbox("Show all campus/landmark pins", value=True)
    zoom = st.slider("Map zoom", 11, 18, 14)

    st.caption("Internet is required for map tiles and OSRM routes.")
    run = st.button(
        "Run / refresh simulation",
        type="primary",
        use_container_width=True,
    )

# Prevent a previously checked emergency toggle from coloring normal journeys.
# Emergency highlighting is active only for the Emergency response scenario.
emergency_priority_active = emergency_priority and scenario == "Emergency response"

# ---------------- Mathematical scenario model ----------------
scenario_factor = SCENARIO_FACTOR[scenario]
demand_norm = clamp(traffic_demand / 100.0)
demand = max(demand_norm, scenario_factor)

flow = max(
    crowd_flow / 100.0,
    scenario_factor if "gathering" in scenario.lower() else 0.0,
)

congestion = (
    clamp(1.0 - measured_speed / reference_speed)
    if reference_speed > 0
    else 1.0
)

density = crowd_count / usable_area
density_norm = clamp(density / 4.0)
traffic_norm = clamp(max(congestion, demand))
flow_norm = clamp(flow)

zone_risk = clamp(
    0.5 * density_norm
    + 0.3 * traffic_norm
    + 0.2 * flow_norm
)

origin = PLACES[origin_name]
destination = PLACES[destination_name]

# ---------------- Retrieve mapped-road routes ----------------
routes = []
routing_error = None

if origin_name == destination_name:
    routing_error = "Select different start and destination locations."
else:
    try:
        with st.spinner("Finding routes along mapped roads..."):
            routes = get_routes(origin, destination)

        # Normal routing always prioritizes the shortest returned route.
        # Crowd overlay is visual-only and must not keep a previous route active.
        routes = sorted(
            routes,
            key=lambda r: r.get("distance", float("inf")),
        )

        if not routes:
            routing_error = "No route returned. Try again or select another place."

    except requests.exceptions.Timeout:
        routing_error = "Routing timed out. The map will still load."
    except requests.exceptions.RequestException as exc:
        routing_error = f"Routing service unavailable: {exc}"
    except (ValueError, KeyError) as exc:
        routing_error = f"Could not read routing response: {exc}"

# Emergency corridor: choose the fastest returned road route.
# This is a simulated priority selection, not emergency dispatch.
emergency_route = (
    min(routes, key=lambda r: r.get("duration", float("inf")))
    if routes else None
)

# ---------------- Dashboard layout ----------------
left, right = st.columns([1, 2])

with left:
    st.subheader("Live scenario indicators")

    a, b = st.columns(2)
    a.metric("Crowd density", f"{density:.2f} people/m²")
    b.metric("Congestion index", f"{congestion:.2f}")

    a, b = st.columns(2)
    a.metric("Zone risk", f"{zone_risk:.3f} / 1.0")
    b.metric("Traffic demand", f"{traffic_demand}%")

    st.markdown("#### Route results")

    if routes:
        shortest = routes[0]
        st.write(
            f"**Shortest returned route:** "
            f"{shortest['distance'] / 1000:.2f} km"
        )
        st.write(
            f"**Estimated time:** {shortest['duration'] / 60:.1f} min"
        )

        if len(routes) > 1:
            alt = routes[1]
            st.write(
                f"**Alternative:** {alt['distance'] / 1000:.2f} km"
                f" · {alt['duration'] / 60:.1f} min"
            )
        else:
            st.caption("Only one route was returned by OSRM.")

        if emergency_priority_active and emergency_route:
            st.write(
                f"**Emergency corridor estimate:** "
                f"{emergency_route['distance'] / 1000:.2f} km"
                f" · {emergency_route['duration'] / 60:.1f} min"
            )
    elif routing_error:
        st.warning(routing_error)

    st.markdown("#### R-risk scoring method")
    st.code(
        "Density = people / usable_area\n"
        "D_norm = min(1, Density / 4)\n"
        "C = clamp(1 - speed / reference_speed)\n"
        "R = 0.5*D_norm + 0.3*T_norm + 0.2*F_norm\n"
        "R is clamped to [0, 1]",
        language="text",
    )

    st.caption(
        "T_norm uses the larger of scenario congestion and selected "
        "traffic demand. F_norm represents the selected crowd-flow "
        "bottleneck. These are configurable demonstration assumptions."
    )

    if block_road:
        st.warning(
            "Closure scenario is enabled. OSRM does not receive a specific "
            "blocked road in this version, so a displayed route may still "
            "pass through the simulated closure."
        )

    if emergency_priority_active:
        st.info(
            "Magenta highlights the fastest route returned by the routing "
            "service as a simulated emergency corridor. Real ambulance or "
            "government dispatch requires verified road access, live closures, "
            "and authorized operational data."
        )


with right:
    st.subheader("OpenStreetMap • Traffic-risk & emergency map")

    m = folium.Map(
        location=CENTER if "CENTER" in globals() else PLACES["ITS Engineering College"],
        zoom_start=zoom,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Campus/landmark pins.
    for name, coord in PLACES.items():
        if show_all_places or name in {
            origin_name, destination_name, crowd_name
        }:
            folium.CircleMarker(
                location=coord,
                radius=5,
                color="#eab308",
                weight=2,
                fill=True,
                fill_color="#facc15",
                fill_opacity=0.9,
                tooltip=name,
                popup=name,
            ).add_to(m)

    # Calculate risk scores for the table only; no red R markers are drawn.
    risk_rows = []
    for name, coord in PLACES.items():
        is_hotspot = name == crowd_name
        score = risk_for_place(
            is_hotspot,
            density_norm,
            traffic_norm,
            flow_norm,
            demand_norm,
        )

        if is_hotspot:
            reason = (
                f"Selected crowd hotspot: {crowd_count:,} people over "
                f"{usable_area:,.0f} m² ({density:.2f} people/m²)"
            )
        else:
            reason = (
                f"Scenario-wide traffic demand {traffic_demand}%, "
                f"congestion index {congestion:.2f}; no local crowd "
                f"count supplied for this location"
            )

        risk_rows.append({
            "Place": name,
            "R score": round(score, 3),
            "Reason": reason,
        })

    # Show crowd hotspot radius as an illustrative zone.
    crowd_coord = PLACES[crowd_name]
    folium.Circle(
        location=crowd_coord,
        radius=max(20, min(500, math.sqrt(usable_area / math.pi))),
        color="#dc2626",
        weight=2,
        fill=True,
        fill_color="#ef4444",
        fill_opacity=0.18,
        tooltip=(
            f"Crowd zone: {crowd_count:,} people; "
            f"density {density:.2f} people/m²"
        ),
    ).add_to(m)

    # Start and destination markers.
    folium.Marker(
        origin,
        tooltip=f"START: {origin_name}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(m)

    folium.Marker(
        destination,
        tooltip=f"DESTINATION: {destination_name}",
        icon=folium.Icon(color="blue", icon="flag"),
    ).add_to(m)

    # Real road-following route geometry returned by OSRM.
    route_colors = ["#1685ff", "#00a86b", "#f59e0b"]

    if emergency_priority_active and emergency_route:
        geometry = emergency_route.get("geometry", {}).get("coordinates", [])
        if geometry:
            coords = [(lat, lon) for lon, lat in geometry]
            folium.PolyLine(
                coords,
                color="#d946ef",
                weight=9,
                opacity=0.95,
                tooltip=(
                    "EMERGENCY PRIORITY CORRIDOR (simulated) | "
                    f"{emergency_route['distance'] / 1000:.2f} km"
                ),
            ).add_to(m)

    # Display shortest route and alternatives.
    for index, route in enumerate(routes[:3]):
        geometry = route.get("geometry", {}).get("coordinates", [])
        if not geometry:
            continue

        coords = [(lat, lon) for lon, lat in geometry]
        color = route_colors[index % len(route_colors)]

        # If the emergency route is already drawn, avoid covering it
        # with an identical route line.
        if emergency_priority_active and route is emergency_route:
            continue

        folium.PolyLine(
            coords,
            color=color,
            weight=6 if index == 0 else 4,
            opacity=0.88,
            tooltip=(
                f"{'Shortest returned route' if index == 0 else f'Alternative {index}'}"
                f" | {route['distance'] / 1000:.2f} km"
                f" | {route['duration'] / 60:.1f} min"
            ),
        ).add_to(m)

    # RED CROWD ACCESS ROUTE:
    # Do not color the entire journey red. Find the nearest point on the
    # selected blue route, then ask OSRM for the short road route from that
    # point to the selected crowded hotspot. This creates the red spur shown
    # in the intended design (the road one would take to reach the crowd).
    # It appears only while the hotspot has a non-zero simulated crowd.
    if crowd_count > 0 and routes:
        crowd_coord = PLACES[crowd_name]
        main_geometry = routes[0].get("geometry", {}).get("coordinates", [])

        if main_geometry:
            # OSRM GeoJSON points are [longitude, latitude].
            main_route_points = [(lat, lon) for lon, lat in main_geometry]

            # Find the nearest point on the selected route to the hotspot.
            def distance_metres(a, b):
                lat1, lon1 = map(math.radians, a)
                lat2, lon2 = map(math.radians, b)
                dlat = lat2 - lat1
                dlon = lon2 - lon1
                h = (
                    math.sin(dlat / 2) ** 2
                    + math.cos(lat1) * math.cos(lat2)
                    * math.sin(dlon / 2) ** 2
                )
                return 2 * 6371000 * math.asin(math.sqrt(min(1.0, h)))

            nearest_route_point = min(
                main_route_points,
                key=lambda point: distance_metres(point, crowd_coord),
            )
            nearest_distance = distance_metres(nearest_route_point, crowd_coord)

            # Avoid drawing a misleading connector if the selected journey
            # is too far from the hotspot. A 1.2 km threshold is illustrative.
            if nearest_distance <= 1200:
                try:
                    access_routes = get_routes(nearest_route_point, crowd_coord)
                    if access_routes:
                        # Use the shortest returned road route for the red spur.
                        access_route = min(
                            access_routes,
                            key=lambda route: route.get("distance", float("inf")),
                        )
                        access_geometry = access_route.get("geometry", {}).get("coordinates", [])

                        if len(access_geometry) >= 2:
                            folium.PolyLine(
                                [(lat, lon) for lon, lat in access_geometry],
                                color="#ef2929",
                                weight=8,
                                opacity=0.98,
                                tooltip=(
                                    f"SIMULATED CROWD ACCESS ROUTE to {crowd_name} "
                                    f"| {crowd_count:,} people"
                                ),
                            ).add_to(m)
                except requests.exceptions.RequestException:
                    st.warning(
                        "Could not fetch the red crowd-access route. "
                        "The main journey route is still displayed."
                    )
            else:
                st.info(
                    f"The selected journey passes about {nearest_distance:.0f} m "
                    f"from {crowd_name}. No red access route is drawn because "
                    "the hotspot is too far from this journey."
                )

    folium.LayerControl().add_to(m)

    st_folium(
        m,
        height=650,
        use_container_width=True,
        returned_objects=[],
    )

st.subheader("Traffic-risk locations")
st.dataframe(
    risk_rows,
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "Map base and route geometry use OpenStreetMap and OSRM. Campus "
    "coordinates are approximate and must be verified. R scores are "
    "scenario calculations, not live traffic observations. This version "
    "does not automatically detect congestion, crowds, blocked roads, "
    "or provide a verified emergency dispatch route."
)
