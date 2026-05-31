# Apex Retail Store Intelligence - System Design & Architecture

This document provides a comprehensive overview of the design principles, architectural choices, and structural layers of the Apex Retail Store Intelligence Platform.

---

## System Architecture Overview

The system is designed as an end-to-end, high-performance retail event ingestion and analytical platform. It captures shopper behavior from camera feeds, extracts structured sightings, performs Re-Identification and trajectory tracking, and calculates business metrics in real-time.

```
       +-------------------------------------------------------+
       |                  Detection Layer                      |
       |  CAM 1: Entry/Exit | CAM 2/4/5: Floor | CAM 3: Billing |
       +----------------------------+--------------------------+
                                    |
                                    | [JSON Event Stream]
                                    v
       +-------------------------------------------------------+
       |                FastAPI Intelligence API               |
       |  POST /events/ingest  |  GET /stores/{id}/metrics     |
       |  GET /health          |  GET /stores/{id}/funnel      |
       |  GET /stores/.../anom |  GET /stores/{id}/heatmap     |
       +----------------------------+--------------------------+
                                    |
            +-----------------------+-----------------------+
            | [Read/Write SQL]                              | [JSON Responses]
            v                                               v
+-----------------------+                       +-----------------------+
|  SQLite Database      |                       |  Live Web Dashboard   |
|  - events table       |                       |  - Glassmorphic UI    |
|  - pos_transactions   |                       |  - Live Event Feed    |
+-----------------------+                       +-----------------------+
```

### 1. The Detection & Tracking Layer
- **Centroid tracking**: Bounding boxes are processed to extract center coordinates. Euclidean distance matrices associate detections frame-to-frame.
- **Visual Re-ID**: Signature extraction hashes aspect-ratio and dominant color bins to maintain patient visitor identities across visual occlusion.
- **Cross-Camera Matching**: Inbound visitor trajectories are correlated temporally between entry threshold zones and merchandise zones, resolving overlapping camera double counting.

### 2. The Ingest & Database Layer
- **SQLite Engine**: Handled via SQLAlchemy to provide transactional reliability. Enforces atomic ACID transactions.
- **Idempotency Safeguards**: Event IDs act as unique primary keys. A double-post of the same event payload is handled gracefully with partial success returns, never causing duplicates.
- **POS Correlation**: Basket transactions from POS CSV logs are aggregated on startup. Standard temporal lookbacks map purchases to visitors in the billing zone 5 minutes prior.

### 3. The Analytics & Anomaly Engine
- **Funnel Stages**: Unit of measure is session. Evaluates traffic flowing from Entry -> Zone Visits -> Billing -> Checkout without double counting.
- **Heatmap normalization**: Uses HSL metrics to project visitor density and dwell indexes on a 0-100 scale.
- **Dynamic Anomalies**: Tracks active queue bottlenecks, historical conversion drops, and zone dormancy.

---

## AI-Assisted Decisions

During the engineering of this store intelligence pipeline, LLMs shaped our technical implementation in three distinct places.

### 1. Ingest Idempotency Strategy
- **What LLM Suggested**: The LLM proposed an in-memory Redis cache to store event IDs with a TTL, checking existence before running database insertions.
- **My Critique & Override**: I overrode the Redis suggestion. Adding Redis introduces operational complexity (network latency, clustering, extra container). Since we selected **SQLite**, we can leverage SQLite's native `UNIQUE` constraints and handle insertions atomically. This keeps the application stateless, keeps the setup to a single database file, and guarantees strict reliability without a secondary caching cluster.

### 2. Time-Relative Anomaly Scanning (Dead Zones)
- **What LLM Suggested**: The LLM wrote a time-based query matching `datetime.utcnow() - interval '30 minutes'` to identify dead merchandise zones.
- **My Critique & Override**: I immediately realized this would fail silently when run on historical CCTV clips (which are recorded on April 10, 2026). A query based on the host system clock would find that *every* zone has been dead for years, triggering a permanent storm of false alarms. I overrode the design to calculate the "current time" as the **maximum event timestamp currently in the database** for that store. This makes the anomaly engine feed-relative and fully historical-aware, enabling robust, accurate evaluations on any recording from any date.

### 3. Funnel Stage 2 Definition
- **What LLM Suggested**: The LLM defined a zone visit if the camera ID was not CAM_ENTRY.
- **My Critique & Override**: I refined this approach. A camera ID is not a reliable indicator of product interest because camera fields of view overlap (e.g. floor camera covers entry or billing partly). I refactored the pipeline to check specific polygonal `zone_id` values (excluding ENTRY, EXIT, and BILLING) defined in our store layout schema. This ensures our zone visit funnel count represents actual merchandise interaction.
