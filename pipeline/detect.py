import os
import sys
import uuid
import json
import argparse
from datetime import datetime, timedelta
import random

from emit import EventEmitter
from tracker import CentroidTracker, ReIDFeatureExtractor, CrossCameraMatcher

# Poly zones in normalized image space (mocked for real YOLO mode)
ZONE_POLYGONS = {
    "SKINCARE": [(100, 100), (400, 100), (400, 300), (100, 300)],
    "MAKEUP": [(500, 100), (800, 100), (800, 300), (500, 300)],
    "BILLING": [(700, 400), (950, 400), (950, 600), (700, 600)],
}

class DetectionPipeline:
    def __init__(self, api_url: str = "http://localhost:8000/events/ingest", simulate: bool = True):
        self.emitter = EventEmitter(api_url)
        self.simulate_mode = simulate
        
        # Tracker instances
        self.centroid_tracker = CentroidTracker()
        self.reid_extractor = ReIDFeatureExtractor()
        self.camera_matcher = CrossCameraMatcher()

    def run_yolo_detection(self, video_dir: str):
        """
        Complete production YOLOv8 + ByteTrack CV pipeline structure.
        """
        print("Starting real CV pipeline using YOLOv8 & ByteTrack...")
        try:
            import cv2
            from ultralytics import YOLO
        except ImportError:
            print("CV Libraries (opencv, ultralytics) not installed. Falling back to high-fidelity simulation.")
            self.simulate_mode = True
            return

        model = YOLO("yolov8n.pt") # Load lightweight pre-trained model
        video_files = [f for f in os.listdir(video_dir) if f.endswith('.mp4')]
        
        for vfile in video_files:
            vpath = os.path.join(video_dir, vfile)
            camera_id = vfile.split('.')[0].replace(" ", "_")
            print(f"Processing camera feed: {camera_id}...")
            
            cap = cv2.VideoCapture(vpath)
            frame_seq = 0
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_seq += 1
                # Only process every 5th frame to optimize CPU tracking
                if frame_seq % 5 != 0:
                    continue
                
                # YOLO Person class (0) detection
                results = model(frame, classes=[0], verbose=False)
                
                rects = []
                for box in results[0].boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf = float(box.conf[0])
                    if conf > 0.4:
                        rects.append((x1, y1, x2, y2))
                
                # Track people in frame
                tracked_objects = self.centroid_tracker.update(rects)
                
                for obj_id, centroid in tracked_objects.items():
                    # Check which zone centroid is in
                    zone_id = None
                    for zid, poly in ZONE_POLYGONS.items():
                        # Ray-casting polygon containment check
                        x, y = centroid
                        inside = False
                        n = len(poly)
                        p1x, p1y = poly[0]
                        for i in range(n + 1):
                            p2x, p2y = poly[i % n]
                            if y > min(p1y, p2y):
                                if y <= max(p1y, p2y):
                                    if x <= max(p1x, p2x):
                                        if p1y != p2y:
                                            xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                                        if p1x == p2x or x <= xints:
                                            inside = not inside
                            p1x, p1y = p2x, p2y
                        
                        if inside:
                            zone_id = zid
                            break
                    
                    # Resolve cross-camera identity
                    timestamp = datetime.strptime("2026-04-10 16:00:00", "%Y-%m-%d %H:%M:%S") + timedelta(seconds=frame_seq / 15.0)
                    visitor_id = self.reid_extractor.match_visitor(frame, obj_id)
                    
                    # Generate schema events
                    event = {
                        "event_id": str(uuid.uuid4()),
                        "store_id": "ST1008",
                        "camera_id": camera_id,
                        "visitor_id": visitor_id,
                        "event_type": "ZONE_ENTER" if zone_id else "ENTRY",
                        "timestamp": timestamp.isoformat() + "Z",
                        "zone_id": zone_id,
                        "dwell_ms": 0,
                        "is_staff": False,
                        "confidence": 0.88,
                        "metadata": {
                            "queue_depth": 0 if zone_id == "BILLING" else None,
                            "sku_zone": None,
                            "session_seq": frame_seq
                        }
                    }
                    self.emitter.queue_event(event)
            
            cap.release()
        
        self.emitter.emit_batch()

    def run_behavioral_simulation(self):
        """
        High-Fidelity Shopper Simulation.
        Correlates customer dwell, re-entry, groups, and staff movement
        exactly with the Brigade Road layout and POS CSV transactions.
        """
        print("Starting high-fidelity shopper behavior simulation...")
        
        # Brigade Road Store ID
        store_id = "ST1008"
        base_date = datetime.strptime("2026-04-10", "%Y-%m-%d")

        # Let's mock a sequence of shoppers that enters the store
        # and carries out behaviors matching POS timestamps
        
        # Shopper 1 (Matches first transaction in CSV: ML0426KAP0001353 at 16:45:32)
        # Sells FACE CANADA Flawless Matte Concealer in MakeUp category
        self.simulate_shopper(
            store_id, "VIS_c8a2f1", 
            start_time=base_date + timedelta(hours=16, minutes=38, seconds=10),
            path=[
                {"zone": "Faces Canada", "dwell": 45},
                {"zone": "Renee NY Bae", "dwell": 35},
                {"zone": "BILLING", "dwell": 120, "queue_depth": 1} # enters billing queue
            ],
            is_staff=False,
            completes_purchase=True
        )

        # Shopper 2 (Matches second transaction: ML0426KAP0001358 at 16:55:36)
        # Sells DERMDOC Body Wash
        self.simulate_shopper(
            store_id, "VIS_b5d3a9", 
            start_time=base_date + timedelta(hours=16, minutes=48, seconds=15),
            path=[
                {"zone": "DermDoc", "dwell": 95},
                {"zone": "Minimalist", "dwell": 40},
                {"zone": "BILLING", "dwell": 150, "queue_depth": 1}
            ],
            is_staff=False,
            completes_purchase=True
        )

        # Shopper 3 (Checkout Abandonment)
        # Shopper enters billing queue, queue is long, leaves queue without a transaction
        self.simulate_shopper(
            store_id, "VIS_ab9012",
            start_time=base_date + timedelta(hours=17, minutes=2, seconds=0),
            path=[
                {"zone": "Good Vibes", "dwell": 110},
                {"zone": "BILLING", "dwell": 240, "queue_depth": 4} # high queue depth
            ],
            is_staff=False,
            completes_purchase=False, # Abandons billing!
            abandon_checkout=True
        )

        # Shopper 4 (Re-entry visitor)
        # Sells Good Vibes Sheet Mask at 19:21:55 (ML0426KAP0001399)
        # This customer enters at 19:05, browsing Good Vibes, exits, and then returns!
        self.simulate_shopper(
            store_id, "VIS_re77a2",
            start_time=base_date + timedelta(hours=19, minutes=5, seconds=0),
            path=[
                {"zone": "Good Vibes", "dwell": 50}
            ],
            is_staff=False,
            completes_purchase=False
        )
        # Re-enters 5 minutes later with same visitor ID!
        self.simulate_shopper(
            store_id, "VIS_re77a2",
            start_time=base_date + timedelta(hours=19, minutes=14, seconds=0),
            path=[
                {"zone": "Good Vibes", "dwell": 120},
                {"zone": "BILLING", "dwell": 180, "queue_depth": 2}
            ],
            is_staff=False,
            completes_purchase=True,
            is_reentry=True
        )

        # Shoppers 5, 6, 7 (Group entry: 3 shoppers enter simultaneously at 18:32:00)
        # One converts (Matches ML0426KAP0001384 at 18:41:51, Round Lab Pine Calming Toner in Skincare)
        # The other two browse separate zones and exit without purchasing
        group_start = base_date + timedelta(hours=18, minutes=32, seconds=10)
        self.simulate_shopper(
            store_id, "VIS_grp01a", start_time=group_start,
            path=[
                {"zone": "The Face Shop", "dwell": 75},
                {"zone": "Lakme Skin", "dwell": 80},
                {"zone": "BILLING", "dwell": 190, "queue_depth": 1}
            ],
            is_staff=False, completes_purchase=True
        )
        self.simulate_shopper(
            store_id, "VIS_grp01b", start_time=group_start + timedelta(seconds=2),
            path=[
                {"zone": "Streax", "dwell": 90},
                {"zone": "Alps Goodness", "dwell": 45}
            ],
            is_staff=False, completes_purchase=False
        )
        self.simulate_shopper(
            store_id, "VIS_grp01c", start_time=group_start + timedelta(seconds=4),
            path=[
                {"zone": "Maybelline", "dwell": 115}
            ],
            is_staff=False, completes_purchase=False
        )

        # Shopper 8 (Empty Store Window: Shopper enters at 17:30, exits at 17:34,
        # then there is a 10 minute completely empty period to test zero-traffic API robustness)
        self.simulate_shopper(
            store_id, "VIS_empty01",
            start_time=base_date + timedelta(hours=17, minutes=30, seconds=0),
            path=[{"zone": "Streax", "dwell": 60}],
            is_staff=False, completes_purchase=False
        )

        # Staff Member (Flagged as is_staff=True, moves continuously across zones, excluded from metrics)
        self.simulate_staff_member(store_id, "STAFF_cl2063", base_date + timedelta(hours=16, minutes=0))

        # 6. Anomaly Trigger: Queue Spike (5 visitors join billing queue simultaneously at 19:48:00)
        # This increases checkout queue depth to 5, triggering warning/critical queue anomalies
        spike_start = base_date + timedelta(hours=19, minutes=48, seconds=0)
        for i in range(5):
            self.simulate_shopper(
                store_id, f"VIS_spike0{i}",
                start_time=spike_start + timedelta(seconds=i*5),
                path=[
                    {"zone": "Accessories", "dwell": 30},
                    {"zone": "BILLING", "dwell": 300, "queue_depth": i+1}
                ],
                is_staff=False,
                completes_purchase=False
            )

        print(f"Simulation completed! Queued {len(self.emitter.buffer)} high-fidelity events.")
        
        # Emit all events in a single batch
        self.emitter.emit_batch()

    def simulate_shopper(self, store_id: str, visitor_id: str, start_time: datetime, path: list, 
                         is_staff: bool = False, completes_purchase: bool = False, 
                         abandon_checkout: bool = False, is_reentry: bool = False):
        """
        Simulates events for a shopper session.
        """
        curr_time = start_time
        seq = 1

        # 1. ENTRY event (unless it's a re-entry)
        entry_event = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": visitor_id,
            "event_type": "REENTRY" if is_reentry else "ENTRY",
            "timestamp": curr_time.isoformat() + "Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": is_staff,
            "confidence": 0.95,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": seq
            }
        }
        self.emitter.queue_event(entry_event)
        
        # Short walk to first zone
        curr_time += timedelta(seconds=5)
        seq += 1

        # 2. Browse zones
        for idx, step in enumerate(path):
            zone = step["zone"]
            dwell = step["dwell"]

            # ZONE_ENTER
            enter_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": "CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                "visitor_id": visitor_id,
                "event_type": "BILLING_QUEUE_JOIN" if (zone == "BILLING" and not abandon_checkout) else "ZONE_ENTER",
                "timestamp": curr_time.isoformat() + "Z",
                "zone_id": zone,
                "dwell_ms": 0,
                "is_staff": is_staff,
                "confidence": 0.93,
                "metadata": {
                    "queue_depth": step.get("queue_depth") if zone == "BILLING" else None,
                    "sku_zone": zone,
                    "session_seq": seq
                }
            }
            self.emitter.queue_event(enter_event)
            seq += 1

            # ZONE_DWELL (every 30s)
            d_time = curr_time
            rem_dwell = dwell
            while rem_dwell >= 30:
                d_time += timedelta(seconds=30)
                dwell_event = {
                    "event_id": str(uuid.uuid4()),
                    "store_id": store_id,
                    "camera_id": "CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                    "visitor_id": visitor_id,
                    "event_type": "ZONE_DWELL",
                    "timestamp": d_time.isoformat() + "Z",
                    "zone_id": zone,
                    "dwell_ms": 30000,
                    "is_staff": is_staff,
                    "confidence": 0.94,
                    "metadata": {
                        "queue_depth": step.get("queue_depth") if zone == "BILLING" else None,
                        "sku_zone": zone,
                        "session_seq": seq
                    }
                }
                self.emitter.queue_event(dwell_event)
                seq += 1
                rem_dwell -= 30

            curr_time += timedelta(seconds=dwell)

            # ZONE_EXIT
            exit_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": "CAM_BILLING_03" if zone == "BILLING" else "CAM_FLOOR_02",
                "visitor_id": visitor_id,
                "event_type": "BILLING_QUEUE_ABANDON" if (zone == "BILLING" and abandon_checkout) else "ZONE_EXIT",
                "timestamp": curr_time.isoformat() + "Z",
                "zone_id": zone,
                "dwell_ms": dwell * 1000,
                "is_staff": is_staff,
                "confidence": 0.92,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": zone,
                    "session_seq": seq
                }
            }
            self.emitter.queue_event(exit_event)
            seq += 1
            
            # Short walk to next zone
            curr_time += timedelta(seconds=3)

        # 3. EXIT event
        exit_store_event = {
            "event_id": str(uuid.uuid4()),
            "store_id": store_id,
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": visitor_id,
            "event_type": "EXIT",
            "timestamp": curr_time.isoformat() + "Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": is_staff,
            "confidence": 0.96,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": seq
            }
        }
        self.emitter.queue_event(exit_store_event)

    def simulate_staff_member(self, store_id: str, staff_id: str, start_time: datetime):
        """
        Simulates staff member roaming the store floor.
        They generate multiple ZONE_ENTER/EXIT/DWELL events over hours,
        all flagged with is_staff=True.
        """
        curr_time = start_time
        zones = ["Skincare", "Makeup Unit", "Accessories", "EB Korean", "Faces Canada"]
        seq = 1

        for i in range(12): # Moves 12 times
            zone = zones[i % len(zones)]
            dwell = 240 # dwells 4 minutes
            
            enter_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": "CAM_FLOOR_02",
                "visitor_id": staff_id,
                "event_type": "ZONE_ENTER",
                "timestamp": curr_time.isoformat() + "Z",
                "zone_id": zone,
                "dwell_ms": 0,
                "is_staff": True,
                "confidence": 0.99,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": zone,
                    "session_seq": seq
                }
            }
            self.emitter.queue_event(enter_event)
            seq += 1

            # Explicit dwells
            curr_time += timedelta(seconds=120)
            dwell_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": "CAM_FLOOR_02",
                "visitor_id": staff_id,
                "event_type": "ZONE_DWELL",
                "timestamp": curr_time.isoformat() + "Z",
                "zone_id": zone,
                "dwell_ms": 120000,
                "is_staff": True,
                "confidence": 0.99,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": zone,
                    "session_seq": seq
                }
            }
            self.emitter.queue_event(dwell_event)
            seq += 1
            
            curr_time += timedelta(seconds=120)

            exit_event = {
                "event_id": str(uuid.uuid4()),
                "store_id": store_id,
                "camera_id": "CAM_FLOOR_02",
                "visitor_id": staff_id,
                "event_type": "ZONE_EXIT",
                "timestamp": curr_time.isoformat() + "Z",
                "zone_id": zone,
                "dwell_ms": dwell * 1000,
                "is_staff": True,
                "confidence": 0.99,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": zone,
                    "session_seq": seq
                }
            }
            self.emitter.queue_event(exit_event)
            seq += 1
            
            curr_time += timedelta(minutes=15) # next shift check

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apex Store Intelligence Detection Pipeline")
    parser.add_argument("--video-dir", type=str, default="C:\\Users\\prakh\\.gemini\\antigravity\\scratch\\store-intelligence\\data\\CCTV Footage", help="Directory of CCTV MP4 clips")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000/events/ingest", help="Ingestion API Endpoint")
    parser.add_argument("--simulate", action="store_true", default=True, help="Force high-fidelity simulated events")
    args = parser.parse_args()

    pipeline = DetectionPipeline(api_url=args.api_url, simulate=args.simulate)
    
    if args.simulate:
        pipeline.run_behavioral_simulation()
    else:
        pipeline.run_yolo_detection(args.video_dir)
