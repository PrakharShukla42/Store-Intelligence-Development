# PROMPT: Generate pytest unit tests for a retail operational anomaly detection service in python. Test anomalies like queue spikes, conversion drops vs baseline, and dead zones with severity and suggested action assertions.
# CHANGES MADE: Tied database schema inputs directly to our SQLite DB engine, mock-seeded events with specific timestamps, and checked Brigade Bangalore operational constraints.

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import uuid

from app.main import app
from app.database import Base, engine, get_db
from app.db_models import DBStoreEvent, DBPOSCommit
from sqlalchemy.orm import sessionmaker

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(name="db_session")
def fixture_db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
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

def test_anomaly_queue_spike(client, db_session):
    store_id = "ST1008"
    base_time = datetime(2026, 4, 10, 16, 0, 0)
    
    # Insert a billing event with queue depth = 5
    db_session.add(DBStoreEvent(
        event_id="e_spike", store_id=store_id, camera_id="CAM_3", visitor_id="VIS_1",
        event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", timestamp=base_time, 
        confidence=0.9, queue_depth=5
    ))
    db_session.commit()
    
    res = client.get(f"/stores/{store_id}/anomalies")
    assert res.status_code == 200
    anomalies = res.json()
    
    # Assert queue spike is detected
    spike = [a for a in anomalies if a["type"] == "BILLING_QUEUE_SPIKE"]
    assert len(spike) == 1
    assert spike[0]["severity"] == "WARN"
    assert "Counter" in spike[0]["description"]
    assert "Counter 2" in spike[0]["suggested_action"]

def test_anomaly_conversion_drop(client, db_session):
    store_id = "ST1008"
    base_time = datetime(2026, 4, 10, 16, 0, 0)
    
    # 20 unique visitors enter, but only 1 completes a purchase (5% conversion vs 16.5% baseline)
    for i in range(20):
        visitor_id = f"VIS_{i}"
        db_session.add(DBStoreEvent(
            event_id=f"ent_{i}", store_id=store_id, camera_id="CAM_1", visitor_id=visitor_id,
            event_type="ENTRY", timestamp=base_time, confidence=0.9
        ))
        # VIS_0 joins billing queue
        if i == 0:
            db_session.add(DBStoreEvent(
                event_id="bill_0", store_id=store_id, camera_id="CAM_3", visitor_id=visitor_id,
                event_type="BILLING_QUEUE_JOIN", zone_id="BILLING", timestamp=base_time + timedelta(seconds=10),
                confidence=0.9
            ))
            
    # Add 1 correlated purchase
    db_session.add(DBPOSCommit(
        transaction_id="TXN_001", store_id=store_id, timestamp=base_time + timedelta(seconds=20),
        basket_value_inr=150.0
    ))
    db_session.commit()
    
    res = client.get(f"/stores/{store_id}/anomalies")
    assert res.status_code == 200
    anomalies = res.json()
    
    drop = [a for a in anomalies if a["type"] == "CONVERSION_DROP"]
    assert len(drop) == 1
    assert drop[0]["severity"] == "CRITICAL" # 5% vs 16.5% is a massive >40% relative drop
    assert "conversion" in drop[0]["description"].lower()

def test_anomaly_dead_zone(client, db_session):
    store_id = "ST1008"
    base_time = datetime(2026, 4, 10, 16, 0, 0)
    
    # Zone skincare was visited early on, but has no visits in the last 40 minutes (stale)
    db_session.add(DBStoreEvent(
        event_id="e_sk", store_id=store_id, camera_id="CAM_2", visitor_id="VIS_1",
        event_type="ZONE_ENTER", zone_id="SKINCARE", timestamp=base_time, confidence=0.9
    ))
    
    # Active latest event is 40 minutes later
    db_session.add(DBStoreEvent(
        event_id="e_latest", store_id=store_id, camera_id="CAM_1", visitor_id="VIS_2",
        event_type="ENTRY", timestamp=base_time + timedelta(minutes=40), confidence=0.9
    ))
    db_session.commit()
    
    res = client.get(f"/stores/{store_id}/anomalies")
    assert res.status_code == 200
    anomalies = res.json()
    
    dead = [a for a in anomalies if a["type"] == "DEAD_ZONE" and "SKINCARE" in a["description"]]
    assert len(dead) == 1
    assert dead[0]["severity"] == "WARN"
    assert "suggested_action" in dead[0]
