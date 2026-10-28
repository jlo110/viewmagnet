"""
Smart Subject Tracking for Vertical Video Crops

Uses YOLOv8 for person detection and MediaPipe for face/pose tracking
to dynamically track subjects when cropping horizontal (16:9) to vertical (9:16).

Key Features:
- Person detection with YOLOv8
- Face tracking with MediaPipe for fine-grained positioning
- Smooth camera motion with interpolation
- Multiple subject handling (follows primary speaker)
- Fallback to center crop when no subjects detected
"""

import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
from enum import Enum

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class TrackingMode(Enum):
    """Subject tracking modes."""
    CENTER = "center"  # Static center crop
    FACE = "face"  # Track faces
    PERSON = "person"  # Track full body
    SPEAKER = "speaker"  # Track likely speaker (largest/most centered face)


@dataclass
class BoundingBox:
    """Bounding box for detected subject."""
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0
    label: str = "person"
    
    @property
    def center_x(self) -> int:
        return self.x + self.width // 2
    
    @property
    def center_y(self) -> int:
        return self.y + self.height // 2
    
    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class FrameTracking:
    """Tracking data for a single frame."""
    frame_number: int
    timestamp: float
    subjects: List[BoundingBox] = field(default_factory=list)
    primary_subject: Optional[BoundingBox] = None
    crop_x: int = 0  # Recommended crop X position


@dataclass
class SubjectTrack:
    """One persistent subject's history across a video segment.

    Built by ``SubjectTracker.track_video_segment_multi`` — each track is a
    "virtual camera" the Studio Camera lane can switch between. ``frames``
    holds the per-detection bbox samples (sparse; only detection-interval
    frames); ``smoothed_crop_x`` is densified to one value per source-video
    frame in the segment so playback can lerp without re-running tracking.
    """
    id: int
    color_hex: str
    label: str
    frames: List[FrameTracking] = field(default_factory=list)
    smoothed_crop_x: List[int] = field(default_factory=list)


@dataclass
class TrackingResult:
    """Complete tracking result for a video segment."""
    frame_trackings: List[FrameTracking] = field(default_factory=list)
    smoothed_crop_positions: List[int] = field(default_factory=list)
    fps: float = 30.0
    frame_width: int = 1920
    frame_height: int = 1080
    tracking_mode: TrackingMode = TrackingMode.CENTER
    # Populated by ``track_video_segment_multi`` only — empty for the
    # legacy single-subject ``track_video_segment`` path used by shorts.
    subject_tracks: List[SubjectTrack] = field(default_factory=list)
    
    def get_crop_at_time(self, timestamp: float) -> int:
        """Get the smoothed crop X position at a given timestamp."""
        if not self.smoothed_crop_positions:
            return (self.frame_width - int(self.frame_height * 9 / 16)) // 2
        
        frame_idx = int(timestamp * self.fps)
        frame_idx = max(0, min(frame_idx, len(self.smoothed_crop_positions) - 1))
        return self.smoothed_crop_positions[frame_idx]
    
    def to_ffmpeg_filter(self, output_width: int = 607, output_height: int = 1080) -> str:
        """
        Generate FFmpeg filter string for dynamic cropping.
        Uses expression-based crop with sendcmd for keyframes.
        """
        if not self.smoothed_crop_positions or len(set(self.smoothed_crop_positions)) == 1:
            # Static crop
            crop_x = self.smoothed_crop_positions[0] if self.smoothed_crop_positions else 656
            return f"crop={output_width}:{output_height}:{crop_x}:0"
        
        # For dynamic tracking, we generate keyframe commands
        # This will be used with FFmpeg's sendcmd filter
        return self._generate_dynamic_filter(output_width, output_height)
    
    def _generate_dynamic_filter(self, output_width: int, output_height: int) -> str:
        """Generate dynamic crop filter with smooth transitions."""
        # Sample keyframes (every 0.5 seconds for smooth motion)
        keyframe_interval = int(self.fps * 0.5)
        keyframes = []
        
        for i in range(0, len(self.smoothed_crop_positions), keyframe_interval):
            time = i / self.fps
            crop_x = self.smoothed_crop_positions[i]
            keyframes.append((time, crop_x))
        
        # For FFmpeg, we'll use a Python expression that interpolates
        # This creates smooth motion between keyframes
        if len(keyframes) < 2:
            return f"crop={output_width}:{output_height}:{keyframes[0][1] if keyframes else 656}:0"
        
        # Build interpolation expression
        # Use linear interpolation between keyframes based on time
        expr_parts = []
        for i in range(len(keyframes) - 1):
            t1, x1 = keyframes[i]
            t2, x2 = keyframes[i + 1]
            
            if i == 0:
                condition = f"lt(t,{t2})"
            elif i == len(keyframes) - 2:
                condition = f"gte(t,{t1})"
            else:
                condition = f"between(t,{t1},{t2})"
            
            # Linear interpolation: x1 + (x2-x1) * (t-t1) / (t2-t1)
            if t2 - t1 > 0:
                interp = f"{x1}+({x2}-{x1})*(t-{t1})/({t2}-{t1})"
            else:
                interp = str(x1)
            
            expr_parts.append(f"if({condition},{interp}")
        
        # Close all the if statements
        crop_expr = "".join(expr_parts) + ")" * (len(expr_parts) - 1)
        
        return f"crop={output_width}:{output_height}:'{crop_expr}':0"
    
    def export_keyframes(self, output_path: str):
        """Export keyframe data for external use."""
        import json
        
        keyframes = []
        keyframe_interval = max(1, int(self.fps * 0.5))
        
        for i in range(0, len(self.smoothed_crop_positions), keyframe_interval):
            keyframes.append({
                "frame": i,
                "time": round(i / self.fps, 3),
                "crop_x": self.smoothed_crop_positions[i]
            })
        
        with open(output_path, 'w') as f:
            json.dump({
                "fps": self.fps,
                "total_frames": len(self.smoothed_crop_positions),
                "frame_width": self.frame_width,
                "frame_height": self.frame_height,
                "keyframes": keyframes
            }, f, indent=2)


class SubjectTracker:
    """
    Smart subject tracking for vertical video crops.
    
    Uses YOLOv8 for person detection and MediaPipe for face tracking.
    Implements smooth camera motion to follow subjects.
    """
    
    def __init__(
        self,
        mode: TrackingMode = TrackingMode.SPEAKER,
        smoothing_window: int = 15,  # Frames for smoothing
        max_velocity: float = 50.0,  # Max crop movement per frame (pixels)
        detection_interval: int = 5,  # Run detection every N frames
    ):
        self.mode = mode
        self.smoothing_window = smoothing_window
        self.max_velocity = max_velocity
        self.detection_interval = detection_interval
        
        # Lazy load models
        self._yolo_model = None
        self._face_detector = None
        self._mp_face_mesh = None
        
    def _load_yolo(self):
        """Lazy load YOLOv8 model."""
        if self._yolo_model is None:
            try:
                from ultralytics import YOLO
                # Use YOLOv8n (nano) for speed, or YOLOv8s for better accuracy
                self._yolo_model = YOLO('yolov8n.pt')
                logger.info("YOLOv8 model loaded successfully")
            except ImportError:
                logger.warning("ultralytics not installed. Install with: pip install ultralytics")
                raise ImportError("YOLOv8 requires ultralytics package")
        return self._yolo_model
    
    def _load_mediapipe_face(self):
        """Lazy load MediaPipe face detection."""
        if self._face_detector is None:
            try:
                import mediapipe as mp
                self._face_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=1,  # 1 for full range (2m), 0 for short range (0.5m)
                    min_detection_confidence=0.5
                )
                logger.info("MediaPipe face detection loaded successfully")
            except ImportError:
                logger.warning("mediapipe not installed. Install with: pip install mediapipe")
                raise ImportError("Face tracking requires mediapipe package")
        return self._face_detector
    
    def detect_faces_mediapipe(self, frame: np.ndarray) -> List[BoundingBox]:
        """Detect faces using MediaPipe."""
        face_detector = self._load_mediapipe_face()
        
        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_detector.process(rgb_frame)
        
        faces = []
        if results.detections:
            h, w = frame.shape[:2]
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                faces.append(BoundingBox(
                    x=int(bbox.xmin * w),
                    y=int(bbox.ymin * h),
                    width=int(bbox.width * w),
                    height=int(bbox.height * h),
                    confidence=detection.score[0],
                    label="face"
                ))
        
        return faces
    
    def detect_persons_yolo(self, frame: np.ndarray) -> List[BoundingBox]:
        """Detect persons using YOLOv8."""
        model = self._load_yolo()
        
        # Run inference
        results = model(frame, classes=[0], verbose=False)  # class 0 = person
        
        persons = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = box.conf[0].cpu().numpy()
                
                persons.append(BoundingBox(
                    x=int(x1),
                    y=int(y1),
                    width=int(x2 - x1),
                    height=int(y2 - y1),
                    confidence=float(conf),
                    label="person"
                ))
        
        return persons
    
    def select_top_n_subjects(
        self,
        faces: List[BoundingBox],
        persons: List[BoundingBox],
        frame_width: int,
        frame_height: int,
        n: int = 4,
    ) -> List[BoundingBox]:
        """Return up to N candidate subjects sorted by the same composite
        score ``select_primary_subject`` uses (confidence + area + center bias).

        Used by ``track_video_segment_multi`` to surface every plausible
        person/face per detection frame so the Studio Camera lane can offer
        the user a real choice of "virtual cameras". Faces still win over
        persons when both are detected (faces are more specific).
        """
        candidates = faces if faces else persons
        if not candidates:
            return []
        frame_center = frame_width // 2

        def score(s: BoundingBox) -> float:
            score = s.confidence * 100
            area_ratio = s.area / (frame_width * frame_height)
            score += area_ratio * 200
            center_distance = abs(s.center_x - frame_center) / frame_center
            score += (1 - center_distance) * 50
            return score

        return sorted(candidates, key=score, reverse=True)[:n]

    def select_primary_subject(
        self,
        faces: List[BoundingBox],
        persons: List[BoundingBox],
        frame_width: int,
        frame_height: int,
        previous_center: Optional[int] = None
    ) -> Optional[BoundingBox]:
        """
        Select the primary subject to track.
        
        Strategy:
        1. Prefer faces over full body detection
        2. Prefer larger subjects (likely closer to camera)
        3. Prefer subjects closer to center
        4. Prefer subjects that maintain continuity with previous frame
        """
        candidates = faces if faces else persons
        
        if not candidates:
            return None
        
        frame_center = frame_width // 2
        
        def score_subject(subject: BoundingBox) -> float:
            # Base score from confidence
            score = subject.confidence * 100
            
            # Bonus for size (larger = more prominent)
            area_ratio = subject.area / (frame_width * frame_height)
            score += area_ratio * 200
            
            # Bonus for being near center
            center_distance = abs(subject.center_x - frame_center) / frame_center
            score += (1 - center_distance) * 50
            
            # Bonus for continuity with previous frame
            if previous_center is not None:
                continuity_distance = abs(subject.center_x - previous_center) / frame_width
                score += (1 - continuity_distance) * 30
            
            return score
        
        # Sort by score and return best
        candidates_sorted = sorted(candidates, key=score_subject, reverse=True)
        return candidates_sorted[0]
    
    def calculate_crop_position(
        self,
        subject: Optional[BoundingBox],
        frame_width: int,
        frame_height: int,
        crop_width: int,
        previous_crop_x: Optional[int] = None
    ) -> int:
        """
        Calculate optimal crop X position to center the subject.
        
        Args:
            subject: Detected subject to center on
            frame_width: Original frame width
            frame_height: Original frame height
            crop_width: Width of the vertical crop (9:16 ratio)
            previous_crop_x: Previous frame's crop X for smoothing
        """
        # Default to center if no subject
        default_crop_x = (frame_width - crop_width) // 2
        
        if subject is None:
            if previous_crop_x is not None:
                # Gradually return to center
                return self._smooth_position(previous_crop_x, default_crop_x)
            return default_crop_x
        
        # Calculate ideal crop to center subject
        ideal_crop_x = subject.center_x - crop_width // 2
        
        # Clamp to valid range
        min_crop_x = 0
        max_crop_x = frame_width - crop_width
        ideal_crop_x = max(min_crop_x, min(ideal_crop_x, max_crop_x))
        
        # Apply velocity limit for smooth motion
        if previous_crop_x is not None:
            delta = ideal_crop_x - previous_crop_x
            if abs(delta) > self.max_velocity:
                delta = self.max_velocity if delta > 0 else -self.max_velocity
            return int(previous_crop_x + delta)
        
        return int(ideal_crop_x)
    
    def _smooth_position(self, current: int, target: int) -> int:
        """Smoothly move from current position toward target."""
        delta = target - current
        if abs(delta) <= self.max_velocity:
            return target
        return int(current + (self.max_velocity if delta > 0 else -self.max_velocity))
    
    def smooth_crop_positions(self, positions: List[int]) -> List[int]:
        """
        Apply smoothing to crop positions for natural camera motion.
        Uses a combination of moving average and velocity limiting.
        """
        if len(positions) <= 1:
            return positions
        
        smoothed = []
        
        for i, pos in enumerate(positions):
            # Get window of positions around current frame
            start = max(0, i - self.smoothing_window // 2)
            end = min(len(positions), i + self.smoothing_window // 2 + 1)
            window = positions[start:end]
            
            # Calculate weighted average (more weight to center)
            weights = np.exp(-0.5 * np.linspace(-2, 2, len(window)) ** 2)
            weighted_avg = np.average(window, weights=weights)
            
            # Apply velocity limit from previous smoothed position
            if smoothed:
                delta = weighted_avg - smoothed[-1]
                if abs(delta) > self.max_velocity:
                    delta = self.max_velocity if delta > 0 else -self.max_velocity
                smoothed.append(int(smoothed[-1] + delta))
            else:
                smoothed.append(int(weighted_avg))
        
        return smoothed
    
    def track_video_segment(
        self,
        video_path: str,
        start_time: float = 0,
        end_time: Optional[float] = None,
        target_ratio: Tuple[int, int] = (9, 16)
    ) -> TrackingResult:
        """
        Track subjects through a video segment.
        
        Args:
            video_path: Path to the video file
            start_time: Start time in seconds
            end_time: End time in seconds (None for full video)
            target_ratio: Target aspect ratio (width, height)
        
        Returns:
            TrackingResult with frame-by-frame crop positions
        """
        cap = cv2.VideoCapture(video_path)
        
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Calculate crop dimensions for target ratio
        crop_height = frame_height
        crop_width = int(crop_height * target_ratio[0] / target_ratio[1])
        
        if crop_width > frame_width:
            # Video is already narrower than target, use full width
            crop_width = frame_width
        
        # Calculate frame range
        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps) if end_time else total_frames
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        frame_trackings = []
        raw_crop_positions = []
        previous_crop_x = None
        previous_center = None
        
        frame_num = start_frame
        logger.info(f"Tracking video segment: frames {start_frame}-{end_frame} ({(end_frame-start_frame)/fps:.1f}s)")
        
        while frame_num < end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Detect subjects (not every frame for performance)
            if frame_num % self.detection_interval == 0:
                faces = []
                persons = []
                
                if self.mode in [TrackingMode.FACE, TrackingMode.SPEAKER]:
                    try:
                        faces = self.detect_faces_mediapipe(frame)
                    except Exception as e:
                        logger.debug(f"Face detection failed: {e}")
                
                if self.mode in [TrackingMode.PERSON, TrackingMode.SPEAKER] and not faces:
                    try:
                        persons = self.detect_persons_yolo(frame)
                    except Exception as e:
                        logger.debug(f"Person detection failed: {e}")
                
                # Select primary subject
                primary = self.select_primary_subject(
                    faces, persons, frame_width, frame_height, previous_center
                )
                
                if primary:
                    previous_center = primary.center_x
                
                # Calculate crop position
                crop_x = self.calculate_crop_position(
                    primary, frame_width, frame_height, crop_width, previous_crop_x
                )
                
                tracking = FrameTracking(
                    frame_number=frame_num,
                    timestamp=frame_num / fps,
                    subjects=faces + persons,
                    primary_subject=primary,
                    crop_x=crop_x
                )
                frame_trackings.append(tracking)
            else:
                # Interpolate between detections
                if raw_crop_positions:
                    crop_x = raw_crop_positions[-1]
                else:
                    crop_x = (frame_width - crop_width) // 2
                
                tracking = FrameTracking(
                    frame_number=frame_num,
                    timestamp=frame_num / fps,
                    crop_x=crop_x
                )
                frame_trackings.append(tracking)
            
            raw_crop_positions.append(tracking.crop_x)
            previous_crop_x = tracking.crop_x
            frame_num += 1
        
        cap.release()
        
        # Apply smoothing to crop positions
        smoothed_positions = self.smooth_crop_positions(raw_crop_positions)
        
        logger.info(f"Tracking complete: {len(frame_trackings)} frames processed")
        
        return TrackingResult(
            frame_trackings=frame_trackings,
            smoothed_crop_positions=smoothed_positions,
            fps=fps,
            frame_width=frame_width,
            frame_height=frame_height,
            tracking_mode=self.mode
        )
    
    # ------------------------------------------------------------------
    # Multi-subject tracking (Studio Camera lane)
    # ------------------------------------------------------------------

    # Colors for up to 8 simultaneous tracks. Picked for high contrast on
    # dark video backgrounds (the bbox overlay sits over the source frame).
    _SUBJECT_PALETTE: Tuple[str, ...] = (
        "#5eead4",  # 1: teal
        "#fb7185",  # 2: rose
        "#fbbf24",  # 3: amber
        "#a78bfa",  # 4: violet
        "#84cc16",  # 5: lime
        "#38bdf8",  # 6: sky
        "#f97316",  # 7: orange
        "#e879f9",  # 8: fuchsia
    )

    @staticmethod
    def _iou(a: BoundingBox, b: BoundingBox) -> float:
        """Intersection-over-union of two bboxes. 0 = disjoint, 1 = identical.

        Used to match detections in frame N to the same physical subject in
        frame N-1, so subject IDs stay stable across the whole clip.
        """
        ax2, ay2 = a.x + a.width, a.y + a.height
        bx2, by2 = b.x + b.width, b.y + b.height
        ix1 = max(a.x, b.x)
        iy1 = max(a.y, b.y)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter = iw * ih
        union = a.area + b.area - inter
        return inter / union if union > 0 else 0.0

    def track_video_segment_multi(
        self,
        video_path: str,
        start_time: float = 0,
        end_time: Optional[float] = None,
        target_ratio: Tuple[int, int] = (9, 16),
        n_subjects: int = 4,
    ) -> TrackingResult:
        """Track up to ``n_subjects`` distinct subjects through a clip with
        stable per-subject IDs.

        The cross-frame ID assignment uses greedy IoU matching against each
        track's most recent bbox; unmatched detections start new tracks
        (capped at ``n_subjects``). Each track's center-x is then independently
        smoothed so the Camera lane can offer a smooth per-subject pan instead
        of a jittery raw-detection feed.

        Returns a ``TrackingResult`` whose ``subject_tracks`` list is populated
        (one entry per matched track). The legacy fields
        (``frame_trackings``/``smoothed_crop_positions``) are also filled with
        track-0's data so callers that don't care about multi-cam still work.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        crop_height = frame_height
        crop_width = int(crop_height * target_ratio[0] / target_ratio[1])
        if crop_width > frame_width:
            crop_width = frame_width

        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps) if end_time else total_frames
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        # Per-track persistent state. `last_bbox` is the most recent detection;
        # `raw_x_by_frame_idx` keeps a sparse map from segment-local frame idx
        # → center_x, used to densify into a per-video-frame smoothed array.
        tracks: List[Dict[str, Any]] = []
        # Track every decoded frame so we can densify smoothing later.
        n_segment_frames = end_frame - start_frame
        # We mirror frame_trackings semantics from the legacy method so the
        # shorts pipeline's downstream consumers see something familiar.
        frame_trackings: List[FrameTracking] = []

        # IoU threshold for "same subject across frames". Looser than 0.5
        # because detection_interval=5 means subjects may move a fair bit
        # between detections.
        IOU_MATCH_THRESHOLD = 0.15

        frame_num = start_frame
        logger.info(
            "studio.tracker.multi.start "
            f"frames={start_frame}-{end_frame} ({(end_frame-start_frame)/fps:.1f}s) "
            f"n_subjects={n_subjects}"
        )

        while frame_num < end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            segment_idx = frame_num - start_frame

            # Detection: only on every detection_interval frame. Between
            # detections we reuse last-known positions per track.
            if frame_num % self.detection_interval == 0:
                faces: List[BoundingBox] = []
                persons: List[BoundingBox] = []
                if self.mode in [TrackingMode.FACE, TrackingMode.SPEAKER]:
                    try:
                        faces = self.detect_faces_mediapipe(frame)
                    except Exception as exc:
                        logger.debug(f"Face detection failed: {exc}")
                if self.mode in [TrackingMode.PERSON, TrackingMode.SPEAKER] and not faces:
                    try:
                        persons = self.detect_persons_yolo(frame)
                    except Exception as exc:
                        logger.debug(f"Person detection failed: {exc}")

                candidates = self.select_top_n_subjects(
                    faces, persons, frame_width, frame_height, n=n_subjects
                )

                # Greedy IoU assignment to existing tracks. Each track gets at
                # most one candidate per detection; each candidate gets at most
                # one track. We pair off in score order so the strongest
                # detection always picks its preferred track first.
                assigned_track_ids: set = set()
                assigned_candidate_idx: set = set()
                pairs: List[Tuple[int, int, float]] = []  # (track_i, cand_i, iou)
                for ti, t in enumerate(tracks):
                    last_box: BoundingBox = t["last_bbox"]
                    for ci, cand in enumerate(candidates):
                        pairs.append((ti, ci, self._iou(last_box, cand)))
                pairs.sort(key=lambda p: p[2], reverse=True)
                for ti, ci, iou in pairs:
                    if iou < IOU_MATCH_THRESHOLD:
                        break
                    if ti in assigned_track_ids or ci in assigned_candidate_idx:
                        continue
                    assigned_track_ids.add(ti)
                    assigned_candidate_idx.add(ci)
                    tracks[ti]["last_bbox"] = candidates[ci]
                    tracks[ti]["raw_x"][segment_idx] = candidates[ci].center_x
                    tracks[ti]["detection_frames"].append(
                        FrameTracking(
                            frame_number=frame_num,
                            timestamp=frame_num / fps,
                            subjects=[candidates[ci]],
                            primary_subject=candidates[ci],
                            crop_x=candidates[ci].center_x,
                        )
                    )

                # Unmatched candidates → new tracks (up to N total).
                for ci, cand in enumerate(candidates):
                    if ci in assigned_candidate_idx:
                        continue
                    if len(tracks) >= n_subjects:
                        break
                    new_id = len(tracks)
                    tracks.append({
                        "id": new_id,
                        "last_bbox": cand,
                        # raw_x: dict[segment_frame_idx -> center_x]. Sparse;
                        # smoothing densifies to a full per-frame array later.
                        "raw_x": {segment_idx: cand.center_x},
                        "detection_frames": [
                            FrameTracking(
                                frame_number=frame_num,
                                timestamp=frame_num / fps,
                                subjects=[cand],
                                primary_subject=cand,
                                crop_x=cand.center_x,
                            )
                        ],
                    })

                # Frame-level summary mirrors legacy `frame_trackings`. We
                # pick the highest-scoring candidate as primary for back-compat.
                primary = candidates[0] if candidates else None
                frame_trackings.append(
                    FrameTracking(
                        frame_number=frame_num,
                        timestamp=frame_num / fps,
                        subjects=candidates,
                        primary_subject=primary,
                        crop_x=primary.center_x if primary else frame_width // 2,
                    )
                )
            else:
                # Between detections: just record an empty placeholder so the
                # frame_trackings array stays one entry per decoded frame.
                frame_trackings.append(
                    FrameTracking(frame_number=frame_num, timestamp=frame_num / fps)
                )

            frame_num += 1

        cap.release()

        # Densify each track's sparse raw_x into a per-frame smoothed series.
        # Missing frames between detections get filled by linear interpolation
        # toward the closest known sample; then `smooth_crop_positions` smooths
        # out the resulting raw curve.
        subject_tracks: List[SubjectTrack] = []
        for t in tracks:
            raw_x_map: Dict[int, int] = t["raw_x"]
            if not raw_x_map:
                continue
            raw_per_frame = self._densify_track_x(
                raw_x_map, n_frames=n_segment_frames, frame_width=frame_width
            )
            # Convert center_x → crop_x (top-left of the crop window).
            raw_crop = [
                max(0, min(frame_width - crop_width, cx - crop_width // 2))
                for cx in raw_per_frame
            ]
            smoothed = self.smooth_crop_positions(raw_crop)
            label = f"Subject {t['id'] + 1}"
            color = self._SUBJECT_PALETTE[t["id"] % len(self._SUBJECT_PALETTE)]
            subject_tracks.append(
                SubjectTrack(
                    id=t["id"],
                    color_hex=color,
                    label=label,
                    frames=t["detection_frames"],
                    smoothed_crop_x=smoothed,
                )
            )

        # Back-compat single-subject crops = track-0's smoothed series.
        smoothed_positions: List[int] = (
            subject_tracks[0].smoothed_crop_x if subject_tracks else []
        )

        logger.info(
            "studio.tracker.multi.done "
            f"tracks={len(subject_tracks)} frames={len(frame_trackings)}"
        )

        return TrackingResult(
            frame_trackings=frame_trackings,
            smoothed_crop_positions=smoothed_positions,
            fps=fps,
            frame_width=frame_width,
            frame_height=frame_height,
            tracking_mode=self.mode,
            subject_tracks=subject_tracks,
        )

    @staticmethod
    def _densify_track_x(
        raw_x_map: Dict[int, int], n_frames: int, frame_width: int
    ) -> List[int]:
        """Fill in `center_x` for every frame in a segment given sparse samples.

        Linear-interpolates between samples; before the first sample and after
        the last we hold the nearest known value (no extrapolation, which would
        amplify detection error at the clip boundaries).
        """
        if n_frames <= 0 or not raw_x_map:
            return [frame_width // 2] * max(0, n_frames)
        sorted_keys = sorted(raw_x_map.keys())
        out: List[int] = [0] * n_frames
        first_x = raw_x_map[sorted_keys[0]]
        last_x = raw_x_map[sorted_keys[-1]]
        cursor = 0
        for i in range(n_frames):
            if i <= sorted_keys[0]:
                out[i] = first_x
                continue
            if i >= sorted_keys[-1]:
                out[i] = last_x
                continue
            # Advance cursor to the segment [sorted_keys[c], sorted_keys[c+1]]
            # that contains `i`.
            while (
                cursor + 1 < len(sorted_keys)
                and sorted_keys[cursor + 1] < i
            ):
                cursor += 1
            a = sorted_keys[cursor]
            b = sorted_keys[cursor + 1]
            xa = raw_x_map[a]
            xb = raw_x_map[b]
            t = (i - a) / max(1, b - a)
            out[i] = int(xa + (xb - xa) * t)
        return out

    def track_multiple_clips(
        self,
        video_path: str,
        clips: List[Tuple[float, float]],  # List of (start_time, end_time)
        target_ratio: Tuple[int, int] = (9, 16)
    ) -> List[TrackingResult]:
        """
        Track subjects for multiple clips efficiently.
        
        Args:
            video_path: Path to video
            clips: List of (start_time, end_time) tuples
            target_ratio: Target aspect ratio
        
        Returns:
            List of TrackingResults, one per clip
        """
        results = []
        
        for i, (start, end) in enumerate(clips):
            logger.info(f"Tracking clip {i+1}/{len(clips)}: {start:.1f}s - {end:.1f}s")
            try:
                result = self.track_video_segment(
                    video_path, start, end, target_ratio
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to track clip {i+1}: {e}")
                # Return empty result for failed clips
                results.append(TrackingResult(tracking_mode=TrackingMode.CENTER))
        
        return results


def generate_tracked_vertical_crop(
    input_path: str,
    output_path: str,
    tracking_result: TrackingResult,
    start_time: float = 0,
    duration: Optional[float] = None
) -> bool:
    """
    Generate vertical video with smart subject tracking using FFmpeg.
    
    Args:
        input_path: Input video path
        output_path: Output video path
        tracking_result: TrackingResult with crop positions
        start_time: Start time in source video
        duration: Duration of clip
    
    Returns:
        True if successful
    """
    import subprocess
    
    # Calculate crop dimensions
    crop_width = int(tracking_result.frame_height * 9 / 16)
    crop_height = tracking_result.frame_height
    
    # Get filter string
    crop_filter = tracking_result.to_ffmpeg_filter(crop_width, crop_height)
    
    # Build FFmpeg command
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_time),
    ]
    
    if duration:
        cmd.extend(['-t', str(duration)])
    
    cmd.extend([
        '-i', input_path,
        '-vf', crop_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '128k',
        output_path
    ])
    
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        logger.info(f"Generated tracked vertical crop: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr.decode() if e.stderr else 'Unknown error'}")
        return False
