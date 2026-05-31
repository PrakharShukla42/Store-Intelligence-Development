from sqlalchemy.orm import Session
from .db_models import DBStoreEvent, DBPOSCommit
from datetime import datetime
import collections

def calculate_store_funnel(db: Session, store_id: str) -> dict:
    """
    Calculates the conversion funnel: Entry -> Zone Visit -> Billing Queue -> Purchase
    using visitor sessions as the unit. Deduplicates re-entries.
    """
    # Get all non-staff events for this store
    events = db.query(DBStoreEvent)\
        .filter(DBStoreEvent.store_id == store_id)\
        .filter(DBStoreEvent.is_staff == False)\
        .order_by(DBStoreEvent.timestamp.asc())\
        .all()

    # Get POS transactions
    pos_txns = db.query(DBPOSCommit)\
        .filter(DBPOSCommit.store_id == store_id)\
        .order_by(DBPOSCommit.timestamp.asc())\
        .all()

    # Group events by visitor_id
    visitor_events = collections.defaultdict(list)
    for e in events:
        visitor_events[e.visitor_id].append(e)

    total_visitors = len(visitor_events)

    # Track how many visitors reached each stage
    stage_entry = 0
    stage_zone_visit = 0
    stage_billing = 0
    stage_purchase = 0

    for visitor_id, evs in visitor_events.items():
        # Every visitor who has events has entered (Stage 1)
        stage_entry += 1
        
        has_zone_visit = False
        has_billing = False
        has_purchase = False
        billing_enters = []

        for e in evs:
            # Stage 2: Product Zone Visit (excludes CAM_ENTRY and cash counter)
            # If the camera is not CAM_ENTRY and zone_id is not null or billing
            # Wait, let's look at the zone_id values.
            # In the layout: EB Korean, Lakme, Makeup, Accessories, etc.
            # So if zone_id is defined and not "BILLING", it's a product zone visit!
            if e.zone_id and e.zone_id != "BILLING" and "CASH" not in e.zone_id.upper():
                has_zone_visit = True
            
            # Stage 3: Billing Queue
            if e.event_type in ["BILLING_QUEUE_JOIN", "ZONE_ENTER"] and e.zone_id == "BILLING":
                has_billing = True
                billing_enters.append(e.timestamp)
            elif e.event_type == "ZONE_ENTER" and e.zone_id and "CASH" in e.zone_id.upper():
                has_billing = True
                billing_enters.append(e.timestamp)

        # Stage 4: Purchase correlation
        if has_billing and billing_enters:
            for b_time in billing_enters:
                for txn in pos_txns:
                    time_diff = (txn.timestamp - b_time).total_seconds()
                    if 0 <= time_diff <= 300: # 5 minutes
                        has_purchase = True
                        break
                if has_purchase:
                    break

        if has_zone_visit:
            stage_zone_visit += 1
        if has_billing:
            stage_billing += 1
        if has_purchase:
            stage_purchase += 1

    # Format the response in a highly professional, clean schema
    stages = [
        {
            "stage": "Entry",
            "count": stage_entry,
            "pct_of_total": 100.0,
            "drop_off_pct": 0.0
        },
        {
            "stage": "Zone Visit",
            "count": stage_zone_visit,
            "pct_of_total": round((stage_zone_visit / stage_entry * 100.0), 2) if stage_entry > 0 else 0.0,
            "drop_off_pct": round((1.0 - (stage_zone_visit / stage_entry)) * 100.0, 2) if stage_entry > 0 else 0.0
        },
        {
            "stage": "Billing Queue",
            "count": stage_billing,
            "pct_of_total": round((stage_billing / stage_entry * 100.0), 2) if stage_entry > 0 else 0.0,
            "drop_off_pct": round((1.0 - (stage_billing / stage_zone_visit)) * 100.0, 2) if stage_zone_visit > 0 else 0.0
        },
        {
            "stage": "Purchase",
            "count": stage_purchase,
            "pct_of_total": round((stage_purchase / stage_entry * 100.0), 2) if stage_entry > 0 else 0.0,
            "drop_off_pct": round((1.0 - (stage_purchase / stage_billing)) * 100.0, 2) if stage_billing > 0 else 0.0
        }
    ]

    return {
        "store_id": store_id,
        "total_sessions": total_visitors,
        "funnel": stages
    }
