"""
hunyuan_generate.py — Hunyuan3D v2 multi-view via fal.ai.

Uploads the 4 rendered OpenGlass reference views, calls Hunyuan3D v2, downloads
the resulting GLB mesh to Friday-glasses/reference/hunyuan_attempt<N>.glb.

Usage:
    uv run python Friday-glasses/blender/hunyuan_generate.py
    uv run python Friday-glasses/blender/hunyuan_generate.py --textured
    uv run python Friday-glasses/blender/hunyuan_generate.py --single   # front only

Reads FAL_AI from /Users/travismoore/Desktop/JARVIS/.env
"""
import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

import fal_client

REPO = Path("/Users/travismoore/Desktop/JARVIS")
REF_DIR = REPO / "Friday-glasses" / "reference"
ENV_FILE = REPO / ".env"


def load_fal_key() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("FAL_AI="):
            return line.split("=", 1)[1].strip()
    sys.exit("FAL_AI= not found in .env")


def next_attempt_path() -> Path:
    for i in range(1, 100):
        p = REF_DIR / f"hunyuan_attempt{i}.glb"
        if not p.exists():
            return p
    sys.exit("too many attempts")


def upload(path: Path) -> str:
    print(f"  uploading {path.name} ... ", end="", flush=True)
    url = fal_client.upload_file(str(path))
    print("ok")
    return url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--textured", action="store_true",
                    help="Generate textured mesh (slower, costs more)")
    ap.add_argument("--single", action="store_true",
                    help="Single-view (front only) instead of multi-view")
    args = ap.parse_args()

    os.environ["FAL_KEY"] = load_fal_key()

    front = REF_DIR / "openglass_front.png"
    right = REF_DIR / "openglass_right.png"
    back  = REF_DIR / "openglass_back.png"
    left  = REF_DIR / "openglass_left.png"
    for p in [front, right, back, left]:
        if not p.exists():
            sys.exit(f"missing input: {p}")

    print("→ uploading reference views")
    front_url = upload(front)
    if not args.single:
        right_url = upload(right)
        back_url  = upload(back)
        left_url  = upload(left)

    if args.single:
        endpoint = "fal-ai/hunyuan3d/v2"
        arguments = {
            "input_image_url": front_url,
            "textured_mesh": args.textured,
        }
    else:
        endpoint = "fal-ai/hunyuan3d/v2/multi-view"
        arguments = {
            "front_image_url": front_url,
            "back_image_url":  back_url,
            "left_image_url":  left_url,
            "textured_mesh":   args.textured,
        }

    print(f"→ calling {endpoint}")
    t0 = time.time()

    def on_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs or []:
                print(f"   [fal] {log['message']}")

    result = fal_client.subscribe(endpoint, arguments=arguments,
                                   with_logs=True, on_queue_update=on_update)
    dt = time.time() - t0
    print(f"← generated in {dt:.1f}s")

    mesh = result.get("model_mesh") or result.get("mesh")
    if not mesh or "url" not in mesh:
        print("unexpected response:", result)
        sys.exit(1)

    out = next_attempt_path()
    print(f"→ downloading {mesh['url']}")
    print(f"   → {out}")
    urllib.request.urlretrieve(mesh["url"], out)

    size_kb = out.stat().st_size // 1024
    print(f"\n✓ wrote {out.name} ({size_kb} KB)")
    print(f"  inspect with: blender --background --python-expr "
          f"\"import bpy; bpy.ops.import_scene.gltf(filepath='{out}')\"")


if __name__ == "__main__":
    main()
