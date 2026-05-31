# Apex Store Intelligence - Retail Analytics Platform

An end-to-end computer vision and real-time store analytics API built for **Apex Retail** to measure and optimize **Offline Store Conversion Rate**.

---

## ⚡ Quick Start (Under 5 Commands)

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

## 🚀 Running the Pipeline (Dual-Mode)

The detection pipeline (`pipeline/detect.py`) processes store camera feeds and pushes events to the API. It features two execution modes:

### 1. High-Fidelity Simulation Mode (Default for evaluation)
Generates high-precision behavioral shopper patterns (including group entries, re-entries, staff movements, and checkout queues) mapped to the **Brigade Road layout** and correlated exactly with the POS transactions:
```bash
# Unix
./pipeline/run.sh

# Windows
pipeline\run.bat
```

### 2. Real YOLOv8 + ByteTrack Mode
If PyTorch, OpenCV, and the `ultralytics` package are installed, it runs a full frame-by-frame person tracker mapping bounding boxes to our store zones layout:
```bash
python pipeline/detect.py --simulate False --video-dir ./data/CCTV\ Footage
```

---

## 📊 Queryable Endpoints

The API is fully production-aware, complete with structured logs, graceful database degradation, and complete idempotency checks:

- `POST /events/ingest` - Accepts batches of up to 500 events. Gracefully ignores duplicate `event_id` tokens (idempotent).
- `GET /stores/{id}/metrics` - Returns unique visitors, conversion rate, zonal dwell times, queue depth, and abandonment rate. (Staff excluded).
- `GET /stores/{id}/funnel` - Session-based conversion funnel (Entry -> Zone Visit -> Billing -> Purchase).
- `GET /stores/{id}/heatmap` - Zone traffic density and dwell times normalized 0–100.
- `GET /stores/{id}/anomalies` - Dynamic operations scanning: flags `BILLING_QUEUE_SPIKE`, `CONVERSION_DROP`, and aisle `DEAD_ZONE` with severity and suggested action plans.
- `GET /health` - Service status, last event ingest timestamp, and `STALE_FEED` warning if feed lags > 10 minutes.

---

## 🧪 Running the Test Suite

Execute the comprehensive test suite verifying the tracking, metrics, and anomaly detection layers:

```bash
# Run pytest across the test suite
python -m pytest tests/
```
