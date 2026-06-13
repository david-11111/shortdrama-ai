from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.comfy_video import generate_comfy_video


DEFAULT_WIDTH = 1088
DEFAULT_HEIGHT = 960
DEFAULT_DURATION = 15
DEFAULT_STEPS = 10
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_PROMPT = (
    "Create a cinematic image-to-video shot that preserves the subject, adds natural camera motion, "
    "realistic lighting, and visible foreground/background depth. No text overlays, no abstract color bars."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real public LTX API smoke generation through SaaS.")
    parser.add_argument("--image", required=True, help="Path to a real reference image. Synthetic test images are not used.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.exists() or not image_path.is_file():
        raise SystemExit(f"Reference image not found: {image_path}")
    if image_path.stat().st_size <= 0:
        raise SystemExit(f"Reference image is empty: {image_path}")

    result = generate_comfy_video(
        {
            "prompt": args.prompt,
            "image_url": str(image_path),
            "duration": args.duration,
            "width": args.width,
            "height": args.height,
            "steps": args.steps,
            "timeout_seconds": args.timeout_seconds,
        },
        provider="wan2.1",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
