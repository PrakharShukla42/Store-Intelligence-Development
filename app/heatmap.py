from sqlalchemy.orm import Session
from .db_models import DBStoreEvent
from sqlalchemy import func
import collections

def calculate_store_heatmap(db: Session, store_id: str) -> dict:
    """
    Computes zone visit frequency and average dwell time, normalized 0-100,
    along with a data_confidence flag (low confidence if <20 unique sessions).
    """
    # 1. Get unique session count to set the data_confidence flag
    unique_sessions = db.query(func.count(func.distinct(DBStoreEvent.visitor_id)))\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.is_staff == False)\
        .scalar() or 0
        
    data_confidence = unique_sessions >= 20

    # Get all non-staff events for this store
    events = db.query(DBStoreEvent)\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.is_staff == False)\
        .order_by(DBStoreEvent.timestamp.asc())\
        .all()

    # Organise events by visitor
    visitor_events = collections.defaultdict(list)
    for e in events:
        visitor_events[e.visitor_id].append(e)

    # Track visits and dwells per zone
    zone_visits = collections.defaultdict(int)
    zone_dwells = collections.defaultdict(list)

    for visitor_id, evs in visitor_events.items():
        visited_zones_in_session = set()
        active_enters = {}
        
        for e in evs:
            if not e.zone_id:
                continue
            
            # Count unique visit per session to prevent noise
            if e.event_type == "ZONE_ENTER":
                active_enters[e.zone_id] = e.timestamp
                if e.zone_id not in visited_zones_in_session:
                    zone_visits[e.zone_id] += 1
                    visited_zones_in_session.add(e.zone_id)
            elif e.event_type == "ZONE_EXIT":
                if e.zone_id in active_enters:
                    enter_time = active_enters.pop(e.zone_id)
                    dur_ms = int((e.timestamp - enter_time).total_seconds() * 1000)
                    if dur_ms > 0:
                        zone_dwells[e.zone_id].append(dur_ms)
            elif e.event_type == "ZONE_DWELL":
                if e.dwell_ms > 0:
                    zone_dwells[e.zone_id].append(e.dwell_ms)

    # Compute raw counts and averages
    raw_heatmap = {}
    all_zones = set(list(zone_visits.keys()) + list(zone_dwells.keys()))

    max_visits = 0
    max_avg_dwell = 0.0

    for zone in all_zones:
        visits = zone_visits.get(zone, 0)
        dwells = zone_dwells.get(zone, [])
        avg_dwell = sum(dwells) / len(dwells) if dwells else 0.0
        
        raw_heatmap[zone] = {
            "visits": visits,
            "avg_dwell_ms": round(avg_dwell, 2)
        }
        
        if visits > max_visits:
            max_visits = visits
        if avg_dwell > max_avg_dwell:
            max_avg_dwell = avg_dwell

    # Normalize metrics to 0-100
    normalized_heatmap = []
    for zone, data in raw_heatmap.items():
        visits = data["visits"]
        avg_dwell = data["avg_dwell_ms"]
        
        norm_visits = (visits / max_visits * 100.0) if max_visits > 0 else 0.0
        norm_dwell = (avg_dwell / max_avg_dwell * 100.0) if max_avg_dwell > 0.0 else 0.0
        
        # Combined composite score (50% visit frequency, 50% dwell duration)
        composite_score = (norm_visits + norm_dwell) / 2.0

        normalized_heatmap.append({
            "zone_id": zone,
            "visits_count": visits,
            "avg_dwell_ms": avg_dwell,
            "normalized_visits": round(norm_visits, 2),
            "normalized_dwell": round(norm_dwell, 2),
            "composite_score": round(composite_score, 2)
        })

    return {
        "store_id": store_id,
        "unique_sessions": unique_sessions,
        "data_confidence": data_confidence,
        "zones": normalized_heatmap
    }
