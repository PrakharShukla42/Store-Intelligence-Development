from sqlalchemy.orm import Session
from .db_models import DBStoreEvent, DBPOSCommit
from .models import StoreEvent
from datetime import datetime
import csv
import os

def get_event_by_id(db: Session, event_id: str):
    return db.query(DBStoreEvent).filter(DBStoreEvent.event_id == event_id).first()

def ingest_single_event(db: Session, event: StoreEvent) -> bool:
    """
    Ingests a single event into the database with idempotency checks.
    Returns True if newly inserted, False if it was a duplicate.
    """
    existing = get_event_by_id(db, event.event_id)
    if existing is not None:
        return False  # Already exists, skip gracefully

    # Extract metadata fields if present
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
    """
    Ingests a batch of events. Returns (processed_newly, duplicate_skipped).
    """
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
            # In case of database constraint error, rollback and mark as duplicate/error
            db.rollback()
            duplicates += 1
    db.commit()
    return processed, duplicates

def import_pos_csv(db: Session, csv_path: str) -> int:
    """
    Parses Brigade_Bangalore CSV and ingests transactions.
    Aggregates NMV by invoice_number to get basket value.
    """
    if not os.path.exists(csv_path):
        print(f"POS CSV file not found at {csv_path}")
        return 0

    # Invoice number -> {store_id, timestamp, total_amt, customer}
    transactions = {}

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            invoice = row.get('invoice_number')
            if not invoice:
                continue
            
            # Format datetime
            order_date = row.get('order_date') # e.g. "10-04-2026"
            order_time = row.get('order_time') # e.g. "16:55:36"
            
            try:
                # order_date is DD-MM-YYYY
                dt_str = f"{order_date} {order_time}"
                timestamp = datetime.strptime(dt_str, "%d-%m-%Y %H:%M:%S")
            except Exception as ex:
                # Default fallback
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

    # Ingest aggregated transactions
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
