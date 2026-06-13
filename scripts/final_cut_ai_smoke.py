from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.final_cut_ai import generate_final_cut_plan
from app.services.final_cut_recipes import get_final_cut_recipe
from app.services.key_pool import key_pool


def main() -> None:
    recipe = get_final_cut_recipe("cinematic_pacing_slow_fast_slow")
    if not recipe:
        raise RuntimeError("recipe not found")

    current_plan = {
        "version": 1,
        "settings": {
            "transition": "fade",
            "burn_subtitles": True,
            "subtitle_source": "prompt",
            "bgm_path": "",
            "bgm_volume": 0.15,
            "cover_title": "",
            "cover_frame_sec": None,
        },
        "clips": [
            {
                "shot_index": 1,
                "order": 1,
                "enabled": True,
                "video_url": "/assets/demo/wide_opening.mp4",
                "prompt": "Dawn mountain wide shot, quiet travel opening with soft mist and calm atmosphere.",
                "duration": 8,
                "trim_start": 0,
                "trim_end": 0,
                "transition": "fade",
                "subtitle": "Morning arrives, and the journey begins.",
            },
            {
                "shot_index": 2,
                "order": 2,
                "enabled": True,
                "video_url": "/assets/demo/hand_food_closeup.mp4",
                "prompt": "Close-up of a hand picking up local street food in a lively market, suitable for faster cuts.",
                "duration": 5,
                "trim_start": 0,
                "trim_end": 0,
                "transition": "fade",
                "subtitle": "The street warms up with smoke and voices.",
            },
            {
                "shot_index": 3,
                "order": 3,
                "enabled": True,
                "video_url": "/assets/demo/sunset_back_view.mp4",
                "prompt": "Sunset back-view medium-wide shot, quiet and reflective, suitable for a lingering ending.",
                "duration": 9,
                "trim_start": 0,
                "trim_end": 0,
                "transition": "fade",
                "subtitle": "Leave the day in the wind.",
            },
        ],
    }

    key_name = None
    try:
        key_name, api_key = key_pool.acquire("doubao")
        result = generate_final_cut_plan(
            api_key,
            recipe=recipe,
            current_plan=current_plan,
            user_instruction=(
                "Edit with a premium slow-fast-slow rhythm. Keep atmosphere in the opening, "
                "increase pace in the middle, and leave breathing room at the end. Do not invent assets."
            ),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        if key_name:
            key_pool.release(key_name)


if __name__ == "__main__":
    main()
