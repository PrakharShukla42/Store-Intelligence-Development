from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import List
from datetime import datetime, timezone
import os
import time
import uuid
import logging
import json

from sqlalchemy.orm import Session
from .database import engine, Base, get_db
from .db_models import DBStoreEvent
from .models import StoreEvent, IngestResponse
from .crud import ingest_events_batch, import_pos_csv
from .metrics import calculate_store_metrics
from .funnel import calculate_store_funnel
from .heatmap import calculate_store_heatmap
from .anomalies import detect_store_anomalies

# Setup structured logger
logger = logging.getLogger("store_intelligence")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Store Intelligence API", version="1.0.0")

# Structured Request Logging Middleware
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    start_time = time.time()
    
    # Generate trace ID if not provided in headers
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    
    # Extract store_id from path if present
    path = request.url.path
    store_id = "N/A"
    parts = path.split("/")
    if "stores" in parts:
        try:
            idx = parts.index("stores")
            if idx + 1 < len(parts):
                store_id = parts[idx + 1]
        except Exception:
            pass
            
    response = await call_next(request)
    
    latency_ms = int((time.time() - start_time) * 1000)
    status_code = response.status_code
    
    # Read event_count from state if set in endpoint
    evt_cnt = getattr(request.state, "event_count", 0)
    
    log_data = {
        "trace_id": trace_id,
        "store_id": store_id,
        "endpoint": path,
        "latency_ms": latency_ms,
        "event_count": evt_cnt,
        "status_code": status_code
    }
    
    logger.info(json.dumps(log_data))
    return response

# Automatically load POS transactions on startup
@app.on_event("startup")
def load_pos_data():
    db = next(get_db())
    # Find the POS transactions CSV
    csv_candidates = [
        "Brigade_Bangalore_10_April_26 (1)bc6219c.csv",
        "../Brigade_Bangalore_10_April_26 (1)bc6219c.csv",
        "C:\\Users\\prakh\\.gemini\\antigravity\\scratch\\store-intelligence\\Brigade_Bangalore_10_April_26 (1)bc6219c.csv"
    ]
    for path in csv_candidates:
        if os.path.exists(path):
            print(f"Loading POS CSV on startup: {path}")
            try:
                import_pos_csv(db, path)
                break
            except Exception as e:
                print(f"Failed to load POS CSV: {e}")

# Serves the live web dashboard
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    # We will embed the HTML directly or read it from a file
    dashboard_path = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    
    # Fallback default dashboard HTML if template is not loaded yet
    return """
    <html>
        <head><title>Apex Store Intelligence</title></head>
        <body style="font-family: sans-serif; text-align: center; padding-top: 100px;">
            <h1>Apex Store Intelligence Dashboard</h1>
            <p>Dashboard UI template is loading, please refresh in a moment...</p>
        </body>
    </html>
    """

@app.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(request: Request, events: List[StoreEvent], db: Session = Depends(get_db)):
    """
    Accepts batches of up to 500 events.
    Validates, deduplicates, stores. Idempotent by event_id.
    """
    # Track the event count for structured middleware logging
    request.state.event_count = len(events)
    
    if len(events) > 500:
        raise HTTPException(status_code=400, detail="Batch size exceeds maximum limit of 500 events.")
    
    processed, skipped = ingest_events_batch(db, events)
    return IngestResponse(
        status="success", 
        processed=processed, 
        errors=skipped, 
        details=[f"Ingested {processed} new events, skipped {skipped} duplicates."]
    )


@app.get("/stores/{store_id}/metrics")
async def get_metrics(store_id: str, db: Session = Depends(get_db)):
    """
    Returns real-time customer and operational metrics for the store.
    """
    try:
        metrics = calculate_store_metrics(db, store_id)
        return metrics
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error": "Database service unavailable", "details": str(e)})

@app.get("/stores/{store_id}/funnel")
async def get_funnel(store_id: str, db: Session = Depends(get_db)):
    """
    Returns the session conversion funnel (Entry -> Zone Visit -> Billing -> Purchase).
    """
    try:
        funnel = calculate_store_funnel(db, store_id)
        return funnel
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error": "Database service unavailable", "details": str(e)})

@app.get("/stores/{store_id}/heatmap")
async def get_heatmap(store_id: str, db: Session = Depends(get_db)):
    """
    Returns zone visit frequencies and dwells, normalized 0-100.
    """
    try:
        heatmap = calculate_store_heatmap(db, store_id)
        return heatmap
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error": "Database service unavailable", "details": str(e)})

@app.get("/stores/{store_id}/anomalies")
async def get_anomalies(store_id: str, db: Session = Depends(get_db)):
    """
    Returns active store anomalies (queue spike, conversion drop, dead zone) with severity and suggested actions.
    """
    try:
        anomalies = detect_store_anomalies(db, store_id)
        return anomalies
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error": "Database service unavailable", "details": str(e)})

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Service status, last event timestamp, and STALE_FEED warning if feed lag > 10 mins.
    """
    # Get the overall last event timestamp across all stores
    last_event = db.query(DBStoreEvent).order_by(DBStoreEvent.timestamp.desc()).first()
    
    status = "ok"
    warnings = []
    last_timestamp = None
    
    if last_event:
        last_timestamp = last_event.timestamp.isoformat()
        # Feed staleness: compare with current real system time
        # Note: since the test clips are historical, the feed might be technically "stale" relative to real time,
        # but to make this production-ready, we check the lag relative to the system clock.
        lag_seconds = (datetime.utcnow() - last_event.timestamp).total_seconds()
        if lag_seconds > 600: # 10 minutes
            status = "warn"
            warnings.append("STALE_FEED: No event feed received in the last 10 minutes.")
            
    return {
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "last_event_timestamp": last_timestamp,
        "warnings": warnings
    }
