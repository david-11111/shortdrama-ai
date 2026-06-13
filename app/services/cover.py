import os
import subprocess
import tempfile

import cv2
import numpy as np

from app.config import FFMPEG


def select_best_frame(video_path: str, scenes: list | None = None,
                      num_candidates: int = 20) -> str:
    tmp_dir = tempfile.mkdtemp(prefix="cover_")
    candidates: list[str] = []

    if scenes:
        timestamps = [(s["start_sec"] + s["end_sec"]) / 2 for s in scenes]
    else:
        cap = cv2.VideoCapture(video_path)
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.release()
        duration = total / fps
        step = duration / (num_candidates + 1)
        timestamps = [step * (i + 1) for i in range(num_candidates)]

    for i, ts in enumerate(timestamps):
        out = os.path.join(tmp_dir, f"frame_{i:03d}.jpg")
        subprocess.run([
            FFMPEG, "-y", "-ss", str(ts), "-i", video_path,
            "-vframes", "1", "-q:v", "2", out,
        ], capture_output=True)
        if os.path.exists(out):
            candidates.append(out)

    if not candidates:
        raise RuntimeError("failed to extract any candidate frames")

    best_path = None
    best_score = -1.0

    scores_brightness = []
    scores_sharpness = []
    scores_contrast = []

    for path in candidates:
        img = cv2.imread(path)
        if img is None:
            scores_brightness.append(0.0)
            scores_sharpness.append(0.0)
            scores_contrast.append(0.0)
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))
        brightness = max(0.0, 1.0 - abs(mean_val - 130) / 130)
        scores_brightness.append(brightness)

        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        scores_sharpness.append(sharpness)

        scores_contrast.append(float(np.std(gray)))

    max_sharp = max(scores_sharpness) or 1.0
    max_contrast = max(scores_contrast) or 1.0

    for i, path in enumerate(candidates):
        s_norm = scores_sharpness[i] / max_sharp
        c_norm = scores_contrast[i] / max_contrast
        score = scores_brightness[i] * 0.3 + s_norm * 0.4 + c_norm * 0.3
        if score > best_score:
            best_score = score
            best_path = path

    for path in candidates:
        if path != best_path:
            os.unlink(path)

    return best_path


def generate_cover(frame_path: str, out_path: str,
                   title: str | None = None, logo_path: str | None = None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    filters = []
    inputs = ["-i", frame_path]

    if title:
        font = "C\\\\:/Windows/Fonts/msyh.ttc"
        safe_title = title.replace("'", "\\'").replace(":", "\\:")
        filters.append(
            f"drawtext=text='{safe_title}':fontfile='{font}'"
            f":fontsize=48:fontcolor=white:borderw=3:bordercolor=black"
            f":x=(w-text_w)/2:y=h-th-40"
        )

    if logo_path and os.path.exists(logo_path):
        inputs.extend(["-i", logo_path])
        filters.append("overlay=W-w-20:20")

    cmd = [FFMPEG, "-y"] + inputs
    if filters:
        cmd.extend(["-vf", ",".join(filters)])
    cmd.extend(["-frames:v", "1", out_path])

    subprocess.run(cmd, capture_output=True, check=True)
    return out_path
