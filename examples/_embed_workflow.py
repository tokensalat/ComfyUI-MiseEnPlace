"""One-off helper: embed each example's API-format workflow JSON into its
screenshot PNG as a "prompt" tEXt chunk - the same key ComfyUI's own
SaveImage node writes (see nodes.py's `metadata.add_text("prompt", ...)`).
The frontend's drag-and-drop handler reads that chunk and reconstructs the
graph via loadApiJson when no full "workflow" chunk is present, so dropping
the screenshot onto the canvas loads it the same way dropping the .json does.

Not part of the node package - run manually after updating a screenshot or
its paired example JSON, then delete the __pycache__ this may leave behind.
"""

import json
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

HERE = Path(__file__).parent

PAIRS = [
    ("feedback_loop.json", "screenshots/feedback_loop.png"),
    ("bundling_roundtrip.json", "screenshots/bundling_roundtrip.png"),
    ("sweep_and_format.json", "screenshots/sweep_and_format.png"),
]

for json_name, png_name in PAIRS:
    json_path = HERE / json_name
    png_path = HERE / png_name

    prompt = json.loads(json_path.read_text(encoding="utf-8"))

    img = Image.open(png_path)
    img.load()

    metadata = PngInfo()
    metadata.add_text("prompt", json.dumps(prompt))

    img.save(png_path, pnginfo=metadata)
    print(f"embedded {json_name} into {png_name}")
