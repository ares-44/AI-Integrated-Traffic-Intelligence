import networkx as nx

def build_graph(venue: dict, traffic: dict) -> nx.Graph:
    graph = nx.Graph()
    for road in venue["roads"]:
        live = traffic.get(road["id"], {})
        if live.get("closed", False):
            continue
        base = float(road["baseline_minutes"])
        # Congestion multiplier grows as relative speed falls; keep routes finite.
        speed = max(float(live.get("relative_speed_pct", 100)), 10.0)
        multiplier = 100.0 / speed
        if live.get("congestion") == "SEVERE":
            multiplier *= 2.0
        graph.add_edge(road["from"], road["to"], weight=base * multiplier,
                       road_id=road["id"], name=road["name"])
    return graph

def recommend_route(venue: dict, traffic: dict, origin: str, destination: str) -> dict:
    graph = build_graph(venue, traffic)
    if origin not in graph or destination not in graph:
        return {"available": False, "reason": "Origin or destination is not in the configured road graph."}
    try:
        nodes = __import__("networkx").shortest_path(graph, origin, destination, weight="weight")
        roads, total = [], 0.0
        for a, b in zip(nodes, nodes[1:]):
            edge = graph[a][b]
            total += edge["weight"]
            roads.append({"road_id": edge["road_id"], "name": edge["name"], "from": a, "to": b})
        return {"available": True, "nodes": nodes, "roads": roads,
                "estimated_minutes": round(total, 2),
                "note": "Prototype estimate from configured baseline times and congestion multipliers; not a live ETA."}
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {"available": False, "reason": "No open route is available in the current demo road graph."}
