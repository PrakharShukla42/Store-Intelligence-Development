# Apex Store Intelligence - Retail Analytics Platform

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/PrakharShukla42/Store-Intelligence-Development)

An end-to-end computer vision and real-time store analytics platform built for **Apex Retail** to measure and optimize **Offline Store Conversion Rate** by bridging the retail store data blind spot.

Repository URL: [https://github.com/PrakharShukla42/Store-Intelligence-Development](https://github.com/PrakharShukla42/Store-Intelligence-Development)

---


## 🚀 Quick Start (Under 5 Commands)

Deploy the entire platform (API, SQLite Database, and Live Glassmorphic Dashboard) with a single command:

```bash
# 1. Start the API and Dashboard services
docker compose up --build -d

# 2. Run the behavioral detection pipeline simulator to stream store events
# (This automatically aggregates and matches the historical POS transactions)
./pipeline/run.sh
```

Done! Open your browser and navigate to:
- **Live Web Dashboard (Part E Bonus)**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📁 Project Directory Structure

The repository is organized following professional microservice layout conventions:

```
/store-intelligence/
├── pipeline/
│   ├── detect.py         # Main detection + high-fidelity simulator
│   ├── tracker.py        # Centroid tracker, Re-ID & cross-camera matcher
│   ├── emit.py           # Ingestion client and HTTP event emitter
│   ├── run.sh            # Unix-friendly simulation stream launcher
│   └── run.bat           # Windows-friendly simulation stream launcher
├── app/
│   ├── main.py           # FastAPI entrypoint & structured request middleware
│   ├── database.py       # SQLite connection and session factory
│   ├── crud.py           # Event ingestion & automated POS CSV startup loader
│   ├── db_models.py      # SQLAlchemy relational database tables
│   ├── models.py         # Pydantic validation schemas
│   ├── metrics.py        # Customer & shop floor analytics engine
│   ├── funnel.py         # Session-based conversion funnel calculation
│   ├── heatmap.py        # Zone visit & dwell HSL-normalized heatmap
│   ├── anomalies.py      # Dynamic operational bottleneck alerting
│   └── templates/
│       └── dashboard.html # Glassmorphic real-time web dashboard
├── tests/
│   ├── test_pipeline.py  # Kalman trajectory, Re-ID & overlap tests
│   ├── test_metrics.py   # API endpoints, staff exclusion & funnel tests
│   └── test_anomalies.py # Dead zones, conversion drops & queue spike tests
├── docs/
│   ├── DESIGN.md         # Plain-language systems architecture & LLM overrides log
│   └── CHOICES.md        # Technical choices (YOLO, SQLite, API) trade-off log
├── Dockerfile            # Container build specification
├── docker-compose.yml    # Single command service orchestrator
├── requirements.txt      # Project library dependencies
└── README.md             # This comprehensive platform guide
```

---

## 🐍 Local IDE Running Instructions

If you are running the project locally inside your IDE (without Docker), you can execute all commands out-of-the-box using your local Python 3.12 path:

### 1. Ingest POS CSV & Start the API Server
The server automatically searches for and aggregates the POS transaction records from `Brigade_Bangalore_10_April_26 (1)bc6219c.csv` on startup, preparing your analytical database:
```bash
& "C:\Users\prakh\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
*Leave this terminal running in the background!*

### 2. Stream Simulated Shopper Behavior
To feed events into the running API and watch your dashboard update live:
```bash
& "C:\Users\prakh\AppData\Local\Programs\Python\Python312\python.exe" pipeline/detect.py --simulate
```

### 3. Run the automated Test Suite
Verify mathematical correctness and endpoint reliability (includes 13 complete unit tests):
```bash
& "C:\Users\prakh\AppData\Local\Programs\Python\Python312\python.exe" -m pytest tests/
```

---

## 📹 Bounding Box Tracking & CV Pipeline

The detection pipeline (`pipeline/detect.py`) operates in two execution modes:

### 1. Real YOLOv8 + ByteTrack Mode
If PyTorch, OpenCV, and the `ultralytics` package are installed, it opens the `.mp4` camera clips, detects shoppers (Class 0: Person), runs **Centroid trajectory tracking** for frame-to-frame box mapping, extracts **Re-ID signatures** (aspect ratios and dominant color histograms) to match identities across camera clips, and resolves overlaps between entry and floor cameras.
```bash
python pipeline/detect.py --simulate False --video-dir ./data/CCTV\ Footage
```

### 2. High-Fidelity Simulation Mode (Default)
Deterministic behavioral shopper stream simulating entries, zone browsing dwells, checkout queues, queue abandonments, re-entries, group entries, and continuous staff patrols. Mapped exactly to the **Brigade Road zone layout** and correlated with the POS timestamp records on **April 10, 2026**.

---

## 🧠 Queryable Intelligence API Endpoints

The API is fully production-aware, featuring **structured request logging** (logging `trace_id`, `store_id`, `endpoint`, `latency_ms`, `event_count`, and `status_code` in JSON for every HTTP call) and **graceful degradation** (returning structured 503 errors on database failures):

- `POST /events/ingest` - Accepts batches of up to 500 events. Gracefully ignores duplicate `event_id` tokens (idempotent).
- `GET /stores/{id}/metrics` - Returns unique visitors, conversion rate, zonal average dwells, checkout queue depth, and abandonment rate. (Staff excluded).
- `GET /stores/{id}/funnel` - Session-based conversion funnel (Entry -> Zone Visit -> Billing Queue -> Purchase) ensuring re-entry deduplication.
- `GET /stores/{id}/heatmap` - Zone visit frequency and dwell times, HSL-normalized to a 0–100 scale for visual grid mapping.
- `GET /stores/{id}/anomalies` - Dynamic operations scanning:
  - `BILLING_QUEUE_SPIKE` (Queue depth > 4, alerts severity WARN / CRITICAL).
  - `CONVERSION_DROP` (Triggers if today's conversion drops by >20% compared to historical average).
  - `DEAD_ZONE` (No visitor activity in a zone in the last 30 minutes).
  - *All anomalies include an actionable `suggested_action` string.*
- `GET /health` - Service status, last event ingest timestamp, and `STALE_FEED` warning if feed lags > 10 minutes.
