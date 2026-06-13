from __future__ import annotations


def inspect_mp4(data: bytes) -> dict:
    boxes: list[str] = []
    handlers: list[str] = []

    def walk(start: int, end: int, depth: int = 0) -> None:
        cursor = start
        while cursor + 8 <= end:
            size = int.from_bytes(data[cursor:cursor + 4], "big")
            box_type = data[cursor + 4:cursor + 8].decode("latin1", errors="replace")
            header = 8
            if size == 1 and cursor + 16 <= end:
                size = int.from_bytes(data[cursor + 8:cursor + 16], "big")
                header = 16
            elif size == 0:
                size = end - cursor
            if size < header or cursor + size > end:
                break
            boxes.append(box_type)
            payload_start = cursor + header
            payload_end = cursor + size
            if box_type == "hdlr" and payload_start + 12 <= payload_end:
                handlers.append(data[payload_start + 8:payload_start + 12].decode("latin1", errors="replace"))
            if depth < 8 and box_type in {"moov", "trak", "mdia", "minf", "stbl", "edts", "udta", "meta"}:
                walk(payload_start + (4 if box_type == "meta" else 0), payload_end, depth + 1)
            cursor += size

    walk(0, len(data))
    return {
        "has_ftyp": "ftyp" in boxes,
        "has_moov": "moov" in boxes,
        "has_mdat": "mdat" in boxes,
        "has_video_track": "vide" in handlers,
        "has_audio_track": "soun" in handlers,
        "box_count": len(boxes),
        "handlers": handlers,
    }
