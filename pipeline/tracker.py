import numpy as np
import uuid
import math

class CentroidTracker:
    """
    Local bounding box tracker using Euclidean distance and trajectory matching.
    """
    def __init__(self, max_disappeared=30):
        self.next_object_id = 0
        self.objects = {}
        self.disappeared = {}
        self.max_disappeared = max_disappeared

    def register(self, centroid):
        obj_id = f"TRK_{uuid.uuid4().hex[:6]}"
        self.objects[obj_id] = centroid
        self.disappeared[obj_id] = 0
        return obj_id

    def deregister(self, obj_id):
        del self.objects[obj_id]
        del self.disappeared[obj_id]

    def update(self, rects):
        """
        Updates tracking bounding boxes and returns mapped track IDs and centroids.
        """
        if len(rects) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)
            return self.objects

        input_centroids = np.zeros((len(rects), 2), dtype="int")
        for (i, (startX, startY, endX, endY)) in enumerate(rects):
            cX = int((startX + endX) / 2.0)
            cY = int((startY + endY) / 2.0)
            input_centroids[i] = (cX, cY)

        if len(self.objects) == 0:
            for i in range(0, len(input_centroids)):
                self.register(input_centroids[i])
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())

            # Bounding box matching using distance matrix
            D = np.linalg.norm(np.array(object_centroids)[:, np.newaxis] - input_centroids, axis=2)

            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue

                obj_id = object_ids[row]
                self.objects[obj_id] = input_centroids[col]
                self.disappeared[obj_id] = 0

                used_rows.add(row)
                used_cols.add(col)

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                obj_id = object_ids[row]
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)

            for col in unused_cols:
                self.register(input_centroids[col])

        return self.objects


class ReIDFeatureExtractor:
    """
    Appearance-based Re-Identification matcher.
    Uses features like color profiles, height-width ratios, and spatial proximity
    to re-identify the same customer across non-overlapping views.
    """
    def __init__(self, match_threshold=0.75):
        self.match_threshold = match_threshold
        # Database of registered visitor profiles: visitor_id -> feature_dict
        self.registered_profiles = {}

    def extract_visual_signature(self, crop) -> dict:
        """
        Extracts color histograms and layout ratios from a bounding box crop.
        (MOCKED for standard CPU run but matches torchreid signature).
        """
        # Return a deterministic color signature
        return {
            "aspect_ratio": 0.42,
            "dominant_color": [128, 64, 255]
        }

    def compute_distance(self, sig1: dict, sig2: dict) -> float:
        """
        Computes cosine similarity between two visual signatures.
        """
        # Bounding box ratio distance + dominant color distance
        ratio_diff = abs(sig1["aspect_ratio"] - sig2["aspect_ratio"])
        color_diff = np.linalg.norm(np.array(sig1["dominant_color"]) - np.array(sig2["dominant_color"])) / 255.0
        similarity = 1.0 - (0.4 * ratio_diff + 0.6 * color_diff)
        return float(similarity)

    def match_visitor(self, crop, fallback_id: str) -> str:
        """
        Tries to match a visual crop to existing registered profiles.
        If matched, returns the existing visitor_id. Else registers a new one.
        """
        sig = self.extract_visual_signature(crop)
        
        best_id = None
        best_score = -1.0

        for visitor_id, profile in self.registered_profiles.items():
            score = self.compute_distance(sig, profile)
            if score > self.match_threshold and score > best_score:
                best_score = score
                best_id = visitor_id

        if best_id:
            # Re-identified! Update feature average
            self.registered_profiles[best_id]["dominant_color"] = list(
                0.8 * np.array(self.registered_profiles[best_id]["dominant_color"]) + 0.2 * np.array(sig["dominant_color"])
            )
            return best_id

        # Register new visitor session token
        visitor_id = f"VIS_{fallback_id.split('_')[-1]}"
        self.registered_profiles[visitor_id] = sig
        return visitor_id


class CrossCameraMatcher:
    """
    Handles camera-overlap deduplication.
    Uses time offsets and entering trajectories to match visitors crossing
    overlapping camera field of views (e.g. CAM 1 entry -> CAM 2 main floor).
    """
    def __init__(self, time_tolerance_sec=5.0):
        self.time_tolerance_sec = time_tolerance_sec
        # Queue of recent exits/entries to correlate
        # (camera_id, visitor_id, timestamp)
        self.recent_sightings = []

    def register_sighting(self, camera_id: str, visitor_id: str, timestamp):
        self.recent_sightings.append({
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "timestamp": timestamp
        })
        # Keep list short
        if len(self.recent_sightings) > 100:
            self.recent_sightings.pop(0)

    def resolve_overlap(self, camera_id: str, current_timestamp) -> str:
        """
        If a new entry is detected on CAM_2 (floor) shortly after CAM_1 (entry),
        resolves and returns the original visitor_id from CAM_1 instead of duplicating.
        """
        for sight in reversed(self.recent_sightings):
            if sight["camera_id"] != camera_id:
                time_lag = (current_timestamp - sight["timestamp"]).total_seconds()
                if 0 <= time_lag <= self.time_tolerance_sec:
                    # Deduplicated: same physical person walking from entry into main floor zone
                    return sight["visitor_id"]
        
        # No match found, generate new visitor token
        return f"VIS_{uuid.uuid4().hex[:6]}"
