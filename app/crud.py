from sqlalchemy.orm import Session
from .db_models import DBStoreEvent, DBPOSCommit
from .models import StoreEvent
from datetime import datetime, timedelta
import uuid
import csv
import os

def get_event_by_id(db: Session, event_id: str):
    return db.query(DBStoreEvent).filter(DBStoreEvent.event_id == event_id).first()

def ingest_single_event(db: Session, event: StoreEvent) -> bool:
    existing = get_event_by_id(db, event.event_id)
    if existing is not None:
        return False

    queue_depth = None
    sku_zone = None
    session_seq = None
    if event.metadata:
        queue_depth = event.metadata.queue_depth
        sku_zone = event.metadata.sku_zone
        session_seq = event.metadata.session_seq

    db_event = DBStoreEvent(
        event_id=event.event_id,
        store_id=event.store_id,
        camera_id=event.camera_id,
        visitor_id=event.visitor_id,
        event_type=event.event_type.value,
        timestamp=event.timestamp,
        zone_id=event.zone_id,
        dwell_ms=event.dwell_ms,
        is_staff=event.is_staff,
        confidence=event.confidence,
        queue_depth=queue_depth,
        sku_zone=sku_zone,
        session_seq=session_seq
    )
    db.add(db_event)
    return True

def ingest_events_batch(db: Session, events: list[StoreEvent]) -> tuple[int, int]:
    processed = 0
    duplicates = 0
    for event in events:
        try:
            is_new = ingest_single_event(db, event)
            if is_new:
                processed += 1
            else:
                duplicates += 1
        except Exception as e:
            db.rollback()
            duplicates += 1
    db.commit()
    return processed, duplicates

def import_pos_csv(db: Session, csv_path: str) -> int:
    if not os.path.exists(csv_path):
        print(f"POS CSV file not found at {csv_path}")
        return 0

    transactions = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            invoice = row.get('invoice_number')
            if not invoice:
                continue
            
            order_date = row.get('order_date')
            order_time = row.get('order_time')
            
            try:
                dt_str = f"{order_date} {order_time}"
                timestamp = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
            except Exception:
                timestamp = datetime.utcnow()
            
            store_id = row.get('store_id', 'ST1008')
            nmv = float(row.get('NMV', 0.0) or 0.0)
            customer = row.get('customer_number', '')

            if invoice not in transactions:
                transactions[invoice] = {
                    'store_id': store_id,
                    'timestamp': timestamp,
                    'basket_value': 0.0,
                    'customer': customer
                }
            transactions[invoice]['basket_value'] += nmv

    inserted = 0
    for txn_id, data in transactions.items():
        existing = db.query(DBPOSCommit).filter(DBPOSCommit.transaction_id == txn_id).first()
        if not existing:
            db_txn = DBPOSCommit(
                transaction_id=txn_id,
                store_id=data['store_id'],
                timestamp=data['timestamp'],
                basket_value_inr=data['basket_value'],
                customer_number=data['customer']
            )
            db.add(db_txn)
            inserted += 1
    
    db.commit()
    print(f"Aggregated {len(transactions)} transactions, inserted {inserted} new ones.")
    return inserted

def seed_store_events(db: Session, store_id: str) -> int:
    """
    Directly seeds high-fidelity shopper behavioral events into the SQLite database.
    """
    # Clear any existing events to prevent duplicates on manual trigger
    db.query(DBStoreEvent).filter(DBStoreEvent.store_id == store_id).delete()
    db.commit()

    base_date = datetime.strptime("2026-04-10", "%Y-%m-%d")
    events_to_add = []

    def queue_simulated_shopper(visitor_id, start_time, path, completes_purchase=False, abandon_checkout=False, is_reentry=False):
        curr_time = start_time
        seq = 1
        
        # 1. Entry
        events_to_add.append(DBStoreEvent(
            event_id=str(uuid.uuid4()), store_id=store_id, camera_id="CAM_ENTRY_01",
            visitor_id=visitor_id, event_type="REENTRY" if is_reentry else "ENTRY",
            timestamp=curr_time, confidence=0.95, session_seq=seq
        ))
        curr_time += timedelta(seconds=5)
        seq += 1

        # 2. Browse
        for step in path:
            zone = step["zone"]
            dwell = step["dwell"]

            # ENTER
            events_to_add.append(DBStoreEvent(
                event_id=str(uuid.uuid4()), store_id=store_id,
                camera_id="CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                visitor_id=visitor_id, event_type="BILLING_QUEUE_JOIN" if (zone == "BILLING" and not abandon_checkout) else "ZONE_ENTER",
                timestamp=curr_time, zone_id=zone, confidence=0.93, sku_zone=zone,
                queue_depth=step.get("queue_depth") if zone == "BILLING" else None,
                session_seq=seq
            ))
            seq += 1

            # DWELLS
            d_time = curr_time
            rem_dwell = dwell
            while rem_dwell >= 30:
                d_time += timedelta(seconds=30)
                events_to_add.append(DBStoreEvent(
                    event_id=str(uuid.uuid4()), store_id=store_id,
                    camera_id="CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                    visitor_id=visitor_id, event_type="ZONE_DWELL",
                    timestamp=d_time, zone_id=zone, confidence=0.94, sku_zone=zone,
                    dwell_ms=30000, queue_depth=step.get("queue_depth") if zone == "BILLING" else None,
                    session_seq=seq
                ))
                seq += 1
                rem_dwell -= 30

            curr_time += timedelta(seconds=dwell)

            # EXIT
            events_to_add.append(DBStoreEvent(
                event_id=str(uuid.uuid4()), store_id=store_id,
                camera_id="CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                visitor_id=visitor_id, event_type="BILLING_QUEUE_ABANDON" if (zone == "BILLING" and abandon_checkout) else "ZONE_EXIT",
                timestamp=curr_time, zone_id=zone, confidence=0.92, sku_zone=zone,
                dwell_ms=dwell * 1000, session_seq=seq
            ))
            seq += 1
            curr_time += timedelta(seconds=3)

        # 3. Store Exit
        events_to_add.append(DBStoreEvent(
            event_id=str(uuid.uuid4()), store_id=store_id, camera_id="CAM_ENTRY_01",
            visitor_id=visitor_id, event_type="EXIT", timestamp=curr_time, confidence=0.96, session_seq=seq
        ))

    # --- Shopper Profiles ---
    # Shopper 1 (Converts on FACE CANADA Concealer)
    queue_simulated_shopper(
        "VIS_c8a2f1", base_date + timedelta(hours=16, minutes=38, seconds=10),
        [{"zone": "Faces Canada", "dwell": 45}, {"zone": "Renee NY Bae", "dwell": 35}, {"zone": "BILLING", "dwell": 120, "queue_depth": 1}],
        completes_purchase=True
    )

    # Shopper 2 (Converts on DERMDOC Body Wash)
    queue_simulated_shopper(
        "VIS_b5d3a9", base_date + timedelta(hours=16, minutes=48, seconds=15),
        [{"zone": "DermDoc", "dwell": 95}, {"zone": "Minimalist", "dwell": 40}, {"zone": "BILLING", "dwell": 150, "queue_depth": 1}],
        completes_purchase=True
    )

    # Shopper 3 (Checkout Abandonment)
    queue_simulated_shopper(
        "VIS_ab9012", base_date + timedelta(hours=17, minutes=2, seconds=0),
        [{"zone": "Good Vibes", "dwell": 110}, {"zone": "BILLING", "dwell": 240, "queue_depth": 4}],
        completes_purchase=False, abandon_checkout=True
    )

    # Shopper 4 (Re-entry, converts on Sheet Mask)
    queue_simulated_shopper(
        "VIS_re77a2", base_date + timedelta(hours=19, minutes=5, seconds=0),
        [{"zone": "Good Vibes", "dwell": 50}]
    )
    queue_simulated_shopper(
        "VIS_re77a2", base_date + timedelta(hours=19, minutes=14, seconds=0),
        [{"zone": "Good Vibes", "dwell": 120}, {"zone": "BILLING", "dwell": 180, "queue_depth": 2}],
        completes_purchase=True, is_reentry=True
    )

    # Shopper 5, 6, 7 (Group entry)
    group_start = base_date + timedelta(hours=18, minutes=32, seconds=10)
    queue_simulated_shopper("VIS_grp01a", group_start, [{"zone": "The Face Shop", "dwell": 75}, {"zone": "Lakme Skin", "dwell": 80}, {"zone": "BILLING", "dwell": 190, "queue_depth": 1}], completes_purchase=True)
    queue_simulated_shopper("VIS_grp01b", group_start + timedelta(seconds=2), [{"zone": "Streax", "dwell": 90}, {"zone": "Alps Goodness", "dwell": 45}])
    queue_simulated_shopper("VIS_grp01c", group_start + timedelta(seconds=4), [{"zone": "Maybelline", "dwell": 115}])

    # Shopper 8 (Empty store boundary)
    queue_simulated_shopper("VIS_empty01", base_date + timedelta(hours=17, minutes=30, seconds=0), [{"zone": "Streax", "dwell": 60}])

    # Staff Member
    staff_id = "STAFF_cl2063"
    staff_time = base_date + timedelta(hours=16, minutes=0)
    zones = ["Skincare", "Makeup Unit", "Accessories", "EB Korean", "Faces Canada"]
    for i in range(8):
        zone = zones[i % len(zones)]
        events_to_add.append(DBStoreEvent(
            event_id=str(uuid.uuid4()), store_id=store_id, camera_id="CAM_FLOOR_02",
            visitor_id=staff_id, event_type="ZONE_ENTER", timestamp=staff_time, zone_id=zone,
            is_staff=True, confidence=0.99, sku_zone=zone, session_seq=i*3+1
        ))
        events_to_add.append(DBStoreEvent(
            event_id=str(uuid.uuid4()), store_id=store_id, camera_id="CAM_FLOOR_02",
            visitor_id=staff_id, event_type="ZONE_DWELL", timestamp=staff_time + timedelta(seconds=120),
            zone_id=zone, is_staff=True, confidence=0.99, sku_zone=zone, dwell_ms=120000, session_seq=i*3+2
        ))
        events_to_add.append(DBStoreEvent(
            event_id=str(uuid.uuid4()), store_id=store_id, camera_id="CAM_FLOOR_02",
            visitor_id=staff_id, event_type="ZONE_EXIT", timestamp=staff_time + timedelta(seconds=240),
            zone_id=zone, is_staff=True, confidence=0.99, sku_zone=zone, dwell_ms=240000, session_seq=i*3+3
        ))
        staff_time += timedelta(minutes=15)

    # 6. Queue Spike
    spike_start = base_date + timedelta(hours=19, minutes=48, seconds=0)
    for i in range(5):
        queue_simulated_shopper(
            f"VIS_spike0{i}", spike_start + timedelta(seconds=i*5),
            [{"zone": "Accessories", "dwell": 30}, {"zone": "BILLING", "dwell": 300, "queue_depth": i+1}]
        )

    # Save to SQLite
    for ev in events_to_add:
        db.add(ev)
    db.commit()
    print(f"Seeded {len(events_to_add)} behavioral events directly into SQLite.")
    return len(events_to_add)
