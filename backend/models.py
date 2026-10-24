from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

Severity = Literal["INFO", "WARNING", "HIGH", "CRITICAL"]

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class ZoneObservation(BaseModel):
    zone_id: str
    people_count: int = Field(ge=0)
    zone_area_m2: float | None = Field(default=None, gt=0)
    incoming_per_min: float = Field(default=0, ge=0)
    outgoing_per_min: float = Field(default=0, ge=0)
    movement_score: float = Field(default=1.0, ge=0, le=1)
    source: Literal["demo", "video", "live"] = "demo"

class TrafficObservation(BaseModel):
    road_id: str
    vehicle_count: int = Field(ge=0)
    relative_speed_pct: float = Field(ge=0, le=100, description="Speed as a percentage of the road's normal baseline")
    queue_seconds: float = Field(default=0, ge=0)
    closed: bool = False
    source: Literal["demo", "video", "live"] = "demo"

class EmergencyRequest(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=64)
    origin: str
    destination: str
    emergency_type: Literal["ambulance", "fire", "police", "other"] = "ambulance"

class AlertAction(BaseModel):
    note: str = Field(default="", max_length=500)
