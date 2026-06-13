from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from app.config import FFMPEG
import subprocess, os

def detect_scenes(file_path: str, preview_dir: str = None, duration_sec: float = 0) -> list:
    video = open_video(file_path)
    sm    = SceneManager()
    sm.add_detector(ContentDetector(threshold=27))
    sm.detect_scenes(video)
    scene_list = sm.get_scene_list()

    if not scene_list and duration_sec > 0:
        from scenedetect import FrameTimecode
        fps = video.frame_rate or 24.0
        scene_list = [(FrameTimecode(0, fps), FrameTimecode(duration_sec, fps))]

    results = []
    for i, (s, e) in enumerate(scene_list):
        start = s.get_seconds()
        end   = e.get_seconds()
        preview = None
        if preview_dir:
            os.makedirs(preview_dir, exist_ok=True)
            preview = os.path.join(preview_dir, f"scene_{i:03d}.jpg")
            mid = (start + end) / 2
            subprocess.run([
                FFMPEG, "-y", "-ss", str(mid), "-i", file_path,
                "-vframes", "1", "-q:v", "3", "-vf", "scale=320:-1", preview
            ], capture_output=True)
        results.append({
            "scene_index": i,
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "preview_image_path": preview
        })

    if hasattr(video, '_cap') and video._cap is not None:
        video._cap.release()

    return results
