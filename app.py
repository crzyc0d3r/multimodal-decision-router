"""Run reproducible inspection fixtures or optional live multimodal decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from assets import inspection_request
from client import evaluate_live, load_fixture
from decisions import route_inspection, validate_answers


def demo_images(directory: Path) -> list[Path]:
    """Draw two simple parcel views; fixture scores do not analyze these pixels."""
    paths = []
    for view in (1, 2):
        image = Image.new("RGB", (320, 320), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((55, 65, 265, 255), fill="#cda46b", outline="black", width=3)
        draw.line((160, 65, 160, 255), fill="#e8ce9c", width=18)
        draw.text((70, 275), f"SYNTHETIC PARCEL VIEW {view}", fill="black")
        path = directory / f"parcel-view-{view}.png"
        image.save(path)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    demo = subparsers.add_parser("demo", help="Replay explicitly simulated scores; no key/network.")
    demo.add_argument("--scenario", choices=("confident", "uncertain"), default="confident")
    live = subparsers.add_parser("live", help="Send your own images to the actual TypeSafe API.")
    live.add_argument("images", type=Path, nargs="+")
    live.add_argument("--model", default="jev-1.14.0")
    args = parser.parse_args()
    try:
        if args.mode == "demo":
            with TemporaryDirectory(prefix="multimodal-parcel-") as temporary:
                request = inspection_request(demo_images(Path(temporary)))
            response = load_fixture(args.scenario)
            provenance = "SIMULATED FIXTURE: fixed scores; no model call or image understanding"
        else:
            request = inspection_request(args.images, args.model)
            response = evaluate_live(request)
            provenance = "LIVE TypeSafe response; experimental multimodal model"
        answers = validate_answers(request, response)
        report = {
            "provenance": provenance,
            "model": response.get("model"),
            "image_evidence_count": len(request["assets"]),
            "questions_in_one_request": len(request["questions"]),
            "decision": route_inspection(answers),
        }
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
