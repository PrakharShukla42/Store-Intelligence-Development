from sqlalchemy.orm import Session
from .db_models import DBStoreEvent, DBPOSCommit
from sqlalchemy import func
from datetime import datetime, timedelta
import collections

def calculate_store_metrics(db: Session, store_id: str) -> dict:
    """
    Computes real-time metrics for a given store.
    """
    # 1. Unique visitors (excluding staff)
    unique_visitors_query = db.query(func.count(func.distinct(DBStoreEvent.visitor_id)))\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.is_staff == False)
    unique_visitors = unique_visitors_query.scalar() or 0

    # Let's get all non-staff events for this store to do in-memory session processing
    events = db.query(DBStoreEvent)\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.is_staff == False)\
        .order_by(DBStoreEvent.timestamp.asc())\
        .all()

    # POS transactions for this store
    pos_txns = db.query(DBPOSCommit)\
        .filter(DBPOSCommit.store_id == store_id)\
        .order_by(DBPOSCommit.timestamp.asc())\
        .all()

    # Organize events by visitor
    visitor_events = collections.defaultdict(list)
    for e in events:
        visitor_events[e.visitor_id].append(e)

    # 2 & 5. Conversion & Abandonment
    # Track billing zone entries and checkout completions
    total_billing_visitors = 0
    converted_billing_visitors = 0

    # Let's identify conversions by looking at visitors who were in the billing zone
    # and had a POS transaction follow within 5 minutes (300 seconds)
    visitor_billing_enters = {}
    for visitor_id, evs in visitor_events.items():
        billing_enters = []
        for e in evs:
            # Look for entering the billing zone
            if e.event_type in ["BILLING_QUEUE_JOIN", "ZONE_ENTER"] and e.zone_id == "BILLING":
                billing_enters.append(e.timestamp)
            elif e.event_type == "ZONE_ENTER" and e.zone_id and "CASH" in e.zone_id.upper():
                billing_enters.append(e.timestamp)
        
        if billing_enters:
            # Shopper entered billing queue
            visitor_billing_enters[visitor_id] = billing_enters
            total_billing_visitors += 1
            
            # Check if any POS transaction correlates with any billing enter time
            converted = False
            for b_time in billing_enters:
                # Is there a POS transaction in the 5 minutes following?
                for txn in pos_txns:
                    time_diff = (txn.timestamp - b_time).total_seconds()
                    if 0 <= time_diff <= 300: # 5 minutes
                        converted = True
                        break
                if converted:
                    break
            
            if converted:
                converted_billing_visitors += 1

    # Conversion rate: Converted visitors / Total unique visitors
    # Handle zero unique visitors
    conversion_rate = (converted_billing_visitors / unique_visitors) if unique_visitors > 0 else 0.0

    # Abandonment rate: (Billing visitors who didn't buy) / (Total billing visitors)
    abandonment_count = total_billing_visitors - converted_billing_visitors
    abandonment_rate = (abandonment_count / total_billing_visitors) if total_billing_visitors > 0 else 0.0

    # 3. Average dwell per zone
    # Let's track zone enter and exit times to calculate absolute dwells,
    # and also accumulate explicit ZONE_DWELL events.
    zone_dwells = collections.defaultdict(list)
    
    for visitor_id, evs in visitor_events.items():
        active_enters = {} # zone_id -> timestamp
        for e in evs:
            if e.event_type == "ZONE_ENTER" and e.zone_id:
                active_enters[e.zone_id] = e.timestamp
            elif e.event_type == "ZONE_EXIT" and e.zone_id:
                if e.zone_id in active_enters:
                    enter_time = active_enters.pop(e.zone_id)
                    dur_ms = int((e.timestamp - enter_time).total_seconds() * 1000)
                    if dur_ms > 0:
                        zone_dwells[e.zone_id].append(dur_ms)
            elif e.event_type == "ZONE_DWELL" and e.zone_id:
                # Accumulate explicit dwell events
                if e.dwell_ms > 0:
                    zone_dwells[e.zone_id].append(e.dwell_ms)

    avg_dwell_per_zone = {}
    for zone_id, dwells in zone_dwells.items():
        avg_dwell_per_zone[zone_id] = round(sum(dwells) / len(dwells), 2)

    # 4. Current Queue Depth
    # Let's count how many people entered the billing zone and have NOT exited yet,
    # or look at the latest BILLING_QUEUE_JOIN metadata queue depth.
    queue_depth = 0
    latest_queue_join = db.query(DBStoreEvent)\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.event_type == "BILLING_QUEUE_JOIN")\
        .order_by(DBStoreEvent.timestamp.desc())\
        .first()
    
    if latest_queue_join and latest_queue_join.queue_depth is not None:
        queue_depth = latest_queue_join.queue_depth
    else:
        # Fallback to estimating based on active visitors in the BILLING zone
        active_in_queue = 0
        for visitor_id, evs in visitor_events.items():
            in_queue = False
            for e in evs:
                if e.event_type in ["BILLING_QUEUE_JOIN", "ZONE_ENTER"] and e.zone_id == "BILLING":
                    in_queue = True
                elif e.event_type == "ZONE_EXIT" and e.zone_id == "BILLING":
                    in_queue = False
            if in_queue:
                active_in_queue += 1
        queue_depth = active_in_queue

    return {
        "unique_visitors": unique_visitors,
        "conversion_rate": round(conversion_rate, 4),
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "queue_depth": queue_depth,
        "abandonment_rate": round(abandonment_rate, 4)
    }
