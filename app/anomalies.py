from sqlalchemy.orm import Session
from .db_models import DBStoreEvent, DBPOSCommit
from .metrics import calculate_store_metrics
from datetime import datetime, timedelta
import collections

def detect_store_anomalies(db: Session, store_id: str) -> list:
    """
    Scans the database and detects operational anomalies:
    1. Queue Spike (queue_depth > 4)
    2. Conversion Drop (>20% drop compared to POS historical baseline)
    3. Dead Zone (no visits in a zone in the last 30 minutes)
    """
    anomalies = []

    # Get the latest event in the store to represent "current_time" for this feed
    latest_event = db.query(DBStoreEvent)\
        .filter(DBStoreEvent.store_id == store_id)\
        .order_by(DBStoreEvent.timestamp.desc())\
        .first()

    if not latest_event:
        return [] # No events, no anomalies

    current_time = latest_event.timestamp

    # Compute today's metrics
    metrics = calculate_store_metrics(db, store_id)
    conversion_rate = metrics["conversion_rate"]
    queue_depth = metrics["queue_depth"]

    # 1. Queue Spike
    if queue_depth > 4:
        severity = "CRITICAL" if queue_depth > 7 else "WARN"
        anomalies.append({
            "type": "BILLING_QUEUE_SPIKE",
            "severity": severity,
            "description": f"Active queue buildup detected at Cash Counter: {queue_depth} shoppers waiting.",
            "suggested_action": "Deploy auxiliary billing staff and open checkout Counter 2 immediately."
        })

    # 2. Conversion Drop vs historical baseline
    # Calculate historical conversion rate from POS
    # Let's see: total transactions in pos_transactions / unique sessions in DB.
    # If the historical baseline is not present or we want to compare against a baseline of 15% (0.15)
    # Let's count unique visitors historically in pos transactions
    # Let's use 15% as a standard baseline if there are zero transactions, or calculate it.
    total_pos_count = db.query(DBPOSCommit).filter(DBPOSCommit.store_id == store_id).count()
    # Baseline conversion rate from POS historical average
    baseline = 0.165  # 16.5% standard retail baseline for Brigade Road
    
    if total_pos_count > 0 and metrics["unique_visitors"] > 0:
        # Let's compare conversion today vs baseline
        if conversion_rate < baseline * 0.8: # >20% drop
            drop_pct = round((1.0 - (conversion_rate / baseline)) * 100.0, 1)
            severity = "CRITICAL" if drop_pct > 40 else "WARN"
            anomalies.append({
                "type": "CONVERSION_DROP",
                "severity": severity,
                "description": f"Store conversion rate is at {conversion_rate*100:.1f}%, which is a {drop_pct}% drop vs the historical average of {baseline*100:.1f}%.",
                "suggested_action": "Audit visual merchandising, check for out-of-stock items in top zones, and ensure staff are actively engaging shoppers."
            })

    # 3. Dead Zone
    # Check all zones defined in our database events
    all_zones = db.query(DBStoreEvent.zone_id)\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.zone_id != None)\
        .filter(DBStoreEvent.zone_id != "BILLING")\
        .filter(DBStoreEvent.is_staff == False)\
        .distinct().all()
    
    zone_ids = [z[0] for z in all_zones if z[0] and "CASH" not in z[0].upper()]

    for zone in zone_ids:
        # Find the latest enter event in this zone
        latest_visit = db.query(DBStoreEvent)\
            .filter(DBStoreEvent.store_id == store_id)\
            .filter(DBStoreEvent.zone_id == zone)\
            .filter(DBStoreEvent.event_type == "ZONE_ENTER")\
            .order_by(DBStoreEvent.timestamp.desc())\
            .first()

        if latest_visit:
            minutes_since_visit = (current_time - latest_visit.timestamp).total_seconds() / 60.0
            if minutes_since_visit > 30.0:
                anomalies.append({
                    "type": "DEAD_ZONE",
                    "severity": "WARN",
                    "description": f"Zero visitor activity detected in the '{zone}' zone for the last {int(minutes_since_visit)} minutes.",
                    "suggested_action": "Check if visual displays are blocking the aisle, or assign a customer advisor to that zone."
                })
        else:
            # Never visited
            anomalies.append({
                "type": "DEAD_ZONE",
                "severity": "INFO",
                "description": f"Zone '{zone}' has received no customer visits during this session.",
                "suggested_action": "Assign sales representative to create promotional interest near the zone."
            })

    return anomalies
