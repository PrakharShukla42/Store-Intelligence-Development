# PROMPT: Generate unit tests for a centroid tracking, Re-ID matching, and cross-camera matching pipeline in python using pytest. Cover frame-to-frame tracking and overlapping camera deduplication.
# CHANGES MADE: Customized the centroid locations, visitor IDs, and camera IDs to exactly match our ST1008 Brigade Bangalore retail layout coordinates and visitor schema.

import pytest
from pipeline.tracker import CentroidTracker, ReIDFeatureExtractor, CrossCameraMatcher

def test_centroid_tracker_register():
    tracker = CentroidTracker()
    rects = [(10, 10, 50, 50)]
    objects = tracker.update(rects)
    
    assert len(objects) == 1
    track_id = list(objects.keys())[0]
    assert track_id.startswith("TRK_")
    assert list(objects.values())[0][0] == 30 # X centroid
    assert list(objects.values())[0][1] == 30 # Y centroid

def test_centroid_tracker_tracking():
    tracker = CentroidTracker()
    # Frame 1
    objects1 = tracker.update([(10, 10, 50, 50)])
    track_id1 = list(objects1.keys())[0]
    
    # Frame 2 - slight movement
    objects2 = tracker.update([(12, 12, 52, 52)])
    track_id2 = list(objects2.keys())[0]
    
    # Track ID should be preserved
    assert track_id1 == track_id2
    assert objects2[track_id2][0] == 32

def test_reid_extractor_registration():
    extractor = ReIDFeatureExtractor()
    
    # First sighting
    vid1 = extractor.match_visitor(None, "TRK_abc1")
    assert vid1.startswith("VIS_")
    
    # Same visual signature (mocked) should match
    vid2 = extractor.match_visitor(None, "TRK_abc2")
    assert vid1 == vid2

def test_cross_camera_matcher_dedup():
    matcher = CrossCameraMatcher(time_tolerance_sec=5.0)
    from datetime import datetime, timedelta
    
    t1 = datetime(2026, 4, 10, 16, 0, 0)
    # Customer enters CAM_ENTRY
    visitor_id = "VIS_tester"
    matcher.register_sighting("CAM_ENTRY_01", visitor_id, t1)
    
    # Same visitor enters CAM_FLOOR_02 3 seconds later
    t2 = t1 + timedelta(seconds=3)
    resolved_id = matcher.resolve_overlap("CAM_FLOOR_02", t2)
    
    assert resolved_id == visitor_id

def test_cross_camera_no_overlap():
    matcher = CrossCameraMatcher(time_tolerance_sec=2.0)
    from datetime import datetime, timedelta
    
    t1 = datetime(2026, 4, 10, 16, 0, 0)
    visitor_id = "VIS_tester"
    matcher.register_sighting("CAM_ENTRY_01", visitor_id, t1)
    
    # Same visitor enters CAM_FLOOR_02 10 seconds later (beyond tolerance)
    t2 = t1 + timedelta(seconds=10)
    resolved_id = matcher.resolve_overlap("CAM_FLOOR_02", t2)
    
    assert resolved_id != visitor_id
