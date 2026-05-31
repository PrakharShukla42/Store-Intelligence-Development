# PROMPT: Generate pytest unit tests for a retail store intelligence metrics API in FastAPI. Check metrics, funnel conversion stages, staff exclusion, queue depth, abandonment, and edge cases like empty store or zero transactions.
# CHANGES MADE: Integrated the FastAPI TestClient, mapped SQLAlchemy session fixtures on SQLite, and validated Brigade Bangalore store-specific schemas.

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import uuid

from app.main import app
from app.database import Base, engine, get_db
from app.db_models import DBStoreEvent, DBPOSCommit
from sqlalchemy.orm import sessionmaker

# Setup test database session
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        # Clear tables before each test
        db.query(DBStoreEvent).delete()
        db.query(DBPOSCommit).delete()
        db.commit()
        yield db
    finally:
        db.close()

@pytest.fixture(name="client")
def fixture_client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)

def test_ingest_events_idempotent(client):
    event_id = str(uuid.uuid4())
    payload = [{
        "event_id": event_id,
        "store_id": "ST1008",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_test1",
        "event_type": "ENTRY",
        "timestamp": "2026-04-10T16:00:00Z",
        "confidence": 0.95
    }]
    
    # First ingest
    res1 = client.post("/events/ingest", json=payload)
    assert res1.status_code == 200
    assert res1.json()["processed"] == 1
    
    # Second duplicate ingest
    res2 = client.post("/events/ingest", json=payload)
    assert res2.status_code == 200
    assert res2.json()["processed"] == 0
    assert res2.json()["errors"] == 1 # 1 skipped duplicate

def test_metrics_calculations(client, db_session):
    store_id = "ST1008"
    base_time = datetime(2026, 4, 10, 16, 0, 0)
    
    # Ingest 1 customer who buys
    c1_events = [
        DBStoreEvent(event_id="e1", store_id=store_id, camera_id="CAM_ENTRY_01", visitor_id="VIS_1", event_type="ENTRY", timestamp=base_time, confidence=0.9),
        DBStoreEvent(event_id="e2", store_id=store_id, camera_id="CAM_FLOOR_02", visitor_id="VIS_1", event_type="ZONE_ENTER", zone_id="SKINCARE", timestamp=base_time + timedelta(seconds=10), confidence=0.9),
        DBStoreEvent(event_id="e3", store_id=store_id, camera_id="CAM_BILLING_03", visitor_id="VIS_1", event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", timestamp=base_time + timedelta(seconds=60), confidence=0.9, queue_depth=1),
        DBStoreEvent(event_id="e4", store_id=store_id, camera_id="CAM_ENTRY_01", visitor_id="VIS_1", event_type="EXIT", timestamp=base_time + timedelta(seconds=180), confidence=0.9)
    ]
    for ev in c1_events:
        db_session.add(ev)
        
    # Ingest 1 staff member (should be excluded)
    staff_events = [
        DBStoreEvent(event_id="e5", store_id=store_id, camera_id="CAM_FLOOR_02", visitor_id="STAFF_1", event_type="ZONE_ENTER", zone_id="SKINCARE", timestamp=base_time, confidence=0.99, is_staff=True)
    ]
    for ev in staff_events:
        db_session.add(ev)
        
    # Ingest Correlated POS transaction
    txn = DBPOSCommit(transaction_id="TX_1", store_id=store_id, timestamp=base_time + timedelta(seconds=90), basket_value_inr=500.0)
    db_session.add(txn)
    
    db_session.commit()
    
    # Check metrics
    res = client.get(f"/stores/{store_id}/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 1 # Excludes staff
    assert data["conversion_rate"] == 1.0 # VIS_1 is converted
    assert data["abandonment_rate"] == 0.0 # Queue is not abandoned

def test_edge_case_empty_store(client):
    res = client.get("/stores/ST_EMPTY/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 0
    assert data["conversion_rate"] == 0.0
    assert data["queue_depth"] == 0

def test_edge_case_staff_only(client, db_session):
    store_id = "ST_STAFF_ONLY"
    # Only staff event
    db_session.add(DBStoreEvent(event_id="s1", store_id=store_id, camera_id="CAM_1", visitor_id="STAFF_X", event_type="ENTRY", timestamp=datetime.utcnow(), confidence=0.98, is_staff=True))
    db_session.commit()
    
    res = client.get(f"/stores/{store_id}/metrics")
    assert res.status_code == 200
    assert res.json()["unique_visitors"] == 0

def test_funnel_stages(client, db_session):
    store_id = "ST1008"
    base_time = datetime(2026, 4, 10, 16, 0, 0)
    
    # 2 shoppers: 1 browses and exits, 1 browses and checkouts
    db_session.add(DBStoreEvent(event_id="f1", store_id=store_id, camera_id="CAM_1", visitor_id="VIS_A", event_type="ENTRY", timestamp=base_time, confidence=0.9))
    db_session.add(DBStoreEvent(event_id="f2", store_id=store_id, camera_id="CAM_2", visitor_id="VIS_A", event_type="ZONE_ENTER", zone_id="MAKEUP", timestamp=base_time + timedelta(seconds=10), confidence=0.9))
    
    db_session.add(DBStoreEvent(event_id="f3", store_id=store_id, camera_id="CAM_1", visitor_id="VIS_B", event_type="ENTRY", timestamp=base_time, confidence=0.9))
    db_session.add(DBStoreEvent(event_id="f4", store_id=store_id, camera_id="CAM_2", visitor_id="VIS_B", event_type="ZONE_ENTER", zone_id="SKINCARE", timestamp=base_time + timedelta(seconds=10), confidence=0.9))
    db_session.add(DBStoreEvent(event_id="f5", store_id=store_id, camera_id="CAM_3", visitor_id="VIS_B", event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", timestamp=base_time + timedelta(seconds=60), confidence=0.9))
    
    # POS correlates for VIS_B
    db_session.add(DBPOSCommit(transaction_id="TX_B", store_id=store_id, timestamp=base_time + timedelta(seconds=120), basket_value_inr=100.0))
    db_session.commit()
    
    res = client.get(f"/stores/{store_id}/funnel")
    assert res.status_code == 200
    funnel = res.json()["funnel"]
    
    # Funnel: Entry(2) -> Zone(2) -> Billing(1) -> Purchase(1)
    assert funnel[0]["count"] == 2 # Entry
    assert funnel[1]["count"] == 2 # Zone Visit
    assert funnel[2]["count"] == 1 # Billing Queue
    assert funnel[3]["count"] == 1 # Purchase
