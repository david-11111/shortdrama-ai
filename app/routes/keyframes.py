"""关键帧端点 — suggest / plan / validate"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import get_current_user

router = APIRouter(prefix="/keyframes", tags=["keyframes"])

_STORAGE = Path("storage")


def _make_frame_id(shot_index: int, n: int) -> str:
    return f"s{shot_index:03d}_f{n:02d}"


def _suggest_uniform(shots: list) -> list:
    plan = []
    for shot in shots:
        idx = int(shot.get("shot_index", 0))
        dur = float(shot.get("duration") or 5.0)
        image_url = shot.get("image_url") or ""
        for n, t in enumerate([0.0, round(dur / 2, 3), round(dur, 3)], 1):
            plan.append({
                "frame_id": _make_frame_id(idx, n),
                "shot_index": idx,
                "t_sec": t,
                "image_url": image_url,
                "source": "uniform",
                "locks": {},
                "reason": "uniform fallback",
            })
    return plan


def _validate_keyframe_plan(plan: list, total_duration: float = 0) -> list[str]:
    errors = []
    seen_ids: set[str] = set()
    for i, frame in enumerate(plan):
        fid = frame.get("frame_id", "")
        if not fid:
            errors.append(f"frame[{i}] missing frame_id")
        elif fid in seen_ids:
            errors.append(f"duplicate frame_id: {fid}")
        else:
            seen_ids.add(fid)
        t = frame.get("t_sec")
        if t is None:
            errors.append(f"frame[{i}] missing t_sec")
        elif total_duration > 0 and float(t) > total_duration:
            errors.append(f"frame[{i}] t_sec={t} exceeds total_duration={total_duration}")
    return errors


@router.post("/suggest")
async def keyframes_suggest(body: dict, current_user: dict = Depends(get_current_user)):
    """AI 关键帧建议，失败时回退到均匀分布。"""
    project_id = body.get("project_id", "")
    shots = body.get("shots") or []
    if not shots:
        raise HTTPException(422, "shots list is empty")

    keyframe_mode = body.get("keyframe_mode", "auto")
    plan: list[dict] = []
    strategy = "auto"
    try:
        for shot in shots:
            idx = int(shot.get("shot_index", 0))
            dur = float(shot.get("duration") or 5.0)
            image_url = shot.get("image_url") or ""
            t_points = [0.0, round(dur, 3)]
            if dur > 5.0:
                t_points.insert(1, round(dur / 2, 3))
            for n, t in enumerate(t_points, 1):
                label = "start" if t == 0 else ("mid" if t < dur else "end")
                plan.append({
                    "frame_id": _make_frame_id(idx, n),
                    "shot_index": idx,
                    "t_sec": t,
                    "image_url": image_url,
                    "source": "auto",
                    "locks": {},
                    "reason": f"auto: {label}",
                })
    except Exception:
        plan = _suggest_uniform(shots)
        strategy = "fallback_uniform"

    return {
        "project_id": project_id,
        "keyframe_mode": keyframe_mode,
        "keyframe_plan_version": 1,
        "keyframe_plan": plan,
        "strategy": strategy,
        "total_frames": len(plan),
    }


@router.put("/plan")
async def keyframes_plan(body: dict, current_user: dict = Depends(get_current_user)):
    """验证并持久化关键帧计划。"""
    project_id = body.get("project_id", "")
    keyframe_plan = body.get("keyframe_plan") or []
    keyframe_mode = body.get("keyframe_mode", "auto")
    version = int(body.get("keyframe_plan_version", 1))

    errors = _validate_keyframe_plan(keyframe_plan)
    if errors:
        raise HTTPException(422, {"message": "keyframe plan validation failed", "errors": errors})

    if project_id:
        plan_dir = _STORAGE / project_id / "keyframes"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plan_dir / f"plan_v{version}.json"
        plan_path.write_text(
            json.dumps({"keyframe_mode": keyframe_mode, "keyframe_plan_version": version, "keyframe_plan": keyframe_plan}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "ok": True,
        "project_id": project_id,
        "keyframe_mode": keyframe_mode,
        "keyframe_plan_version": version,
        "total_frames": len(keyframe_plan),
    }


@router.post("/validate")
async def keyframes_validate(body: dict, current_user: dict = Depends(get_current_user)):
    """验证关键帧计划，返回错误详情。"""
    project_id = body.get("project_id", "")
    keyframe_plan = body.get("keyframe_plan") or []
    total_duration = float(body.get("total_duration") or 0)

    errors = _validate_keyframe_plan(keyframe_plan, total_duration)
    if errors:
        return {"valid": False, "project_id": project_id, "error_count": len(errors), "errors": errors}
    return {"valid": True, "project_id": project_id, "error_count": 0, "errors": []}
