from backend.analytics import crowd_metrics, traffic_metrics

def test_crowd_density_and_risk():
    result = crowd_metrics({"zone_id":"Z","people_count":180,"zone_area_m2":100,
                            "incoming_per_min":10,"outgoing_per_min":2,"movement_score":0.8,"source":"demo"},
                           {"area_m2":100,"capacity_people":200})
    assert result["density_people_m2"] == 1.8
    assert result["occupancy_pct"] == 90.0
    assert result["risk"] == "HIGH"

def test_traffic_severe():
    result = traffic_metrics({"road_id":"R","vehicle_count":40,"relative_speed_pct":15,"queue_seconds":200,"closed":False})
    assert result["congestion"] == "SEVERE"
