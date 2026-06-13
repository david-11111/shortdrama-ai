import subprocess
from pathlib import Path

from app.config import FFMPEG, FFPROBE


def probe(file_path: str) -> dict:
    result = subprocess.run(
        [FFPROBE, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if not result.stdout:
        raise RuntimeError(f"ffprobe returned no output for: {file_path}\nstderr: {result.stderr}")

    import json
    data = json.loads(result.stdout)
    fmt = data.get('format', {})
    video = next((stream for stream in data.get('streams', []) if stream.get('codec_type') == 'video'), {})
    audio = next((stream for stream in data.get('streams', []) if stream.get('codec_type') == 'audio'), {})

    fps = 0.0
    frame_rate = video.get('r_frame_rate', '')
    if '/' in frame_rate:
        numerator, denominator = frame_rate.split('/')
        fps = round(float(numerator) / float(denominator), 3) if float(denominator) else 0.0

    return {
        'file_name': Path(file_path).name,
        'file_path': file_path,
        'file_size': int(fmt.get('size', 0)),
        'duration_sec': float(fmt.get('duration', 0)),
        'width': video.get('width'),
        'height': video.get('height'),
        'fps': fps,
        'video_codec': video.get('codec_name'),
        'audio_codec': audio.get('codec_name'),
        'bitrate': int(fmt.get('bit_rate', 0)),
        'has_audio': 1 if audio else 0,
    }


def extract_audio(file_path: str, out_path: str):
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [FFMPEG, '-y', '-i', file_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(out_file)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if result.returncode != 0 or not out_file.exists():
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr.strip()}")
    return str(out_file)
