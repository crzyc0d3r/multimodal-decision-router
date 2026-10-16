"""Prepare still images and construct TypeSafe asset references."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 16 * 1024 * 1024


def image_asset(path: Path) -> tuple[str, dict]:
    """Read PNG/JPEG, rotate upright, resize/pad, then encode baseline JPEG."""
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Image exceeds 16 MiB: {path.name}")
    try:
        with Image.open(path) as original:
            if original.format not in {"PNG", "JPEG"}:
                raise ValueError("Only PNG and JPEG still images are supported.")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("Animated images are not supported.")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1568, 1568))
            # Padding preserves the image's proportions and meets both minimum sides.
            if min(image.size) < 280:
                image = ImageOps.pad(
                    image, (max(280, image.width), max(280, image.height)),
                    color="white", method=Image.Resampling.LANCZOS,
                )
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=90, progressive=False)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Cannot decode image: {path.name}") from exc
    data = buffer.getvalue()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Prepared image exceeds 16 MiB.")
    reference = str(uuid4())
    return reference, {
        "type": "image", "format": "jpg",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def inspection_request(paths: list[Path], model: str = "jev-1.14.0") -> dict:
    """Batch independent typed questions against all supplied image evidence."""
    if not paths:
        raise ValueError("Provide at least one image.")
    assets, evidence = {}, []
    for index, path in enumerate(paths, 1):
        reference, asset = image_asset(path)
        assets[reference] = asset
        evidence.append({"view": index, "image": reference})
    return {
        "model": model,
        "state": {"task": "Inspect one parcel using all views.", "evidence": evidence},
        "assets": assets,
        "questions": {
            "condition": {
                "type": "choice",
                "instructions": "What is the parcel condition visible in `evidence`?",
                "criteria": {
                    "intact": "No visible damage to the parcel.",
                    "damaged": "Visible tears, dents, crushing, or other damage.",
                    "unclear": "The available views do not establish the condition.",
                },
            },
            "severity": {
                "type": "score",
                "instructions": "Rate visible parcel damage in `evidence`.",
                "criteria": ["No visible damage", "Minor damage", "Major damage"],
            },
            "needs_review": {
                "type": "noul",
                "instructions": "Do conflicting or obstructed views require a human inspection?",
            },
        },
    }
