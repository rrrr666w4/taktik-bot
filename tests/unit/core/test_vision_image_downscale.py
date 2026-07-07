"""Vision images are downscaled before being sent to the (paid) vision model.

Device screenshots are ~1080x2220 PNGs; sent raw they cost ~6 Gemini tiles (~1550 image
tokens) per profile/post analysis. Capping the long edge at VISION_IMAGE_MAX_EDGE drops a
portrait shot to ~2 tiles while keeping the width legible, cutting the dominant slice of
each vision call's cost.
"""

import base64
import io

import pytest

from taktik.core.app.ai.providers.openrouter import AIService, VISION_IMAGE_MAX_EDGE

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _service():
    # Bypass __init__ (needs an API key): _image_for_vision only touches the filesystem + PIL.
    return object.__new__(AIService)


def _decode(data_url: str):
    assert data_url.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return Image.open(io.BytesIO(raw))


def test_downscales_a_device_screenshot(tmp_path):
    src = tmp_path / "profile.png"
    Image.new("RGB", (1080, 2220), (120, 60, 200)).save(src, format="PNG")

    out = _service()._image_for_vision(str(src))
    img = _decode(out)

    # Long edge capped, aspect ratio preserved (portrait stays portrait).
    assert max(img.size) <= VISION_IMAGE_MAX_EDGE
    assert img.height > img.width
    # 1080x2220 -> 747x1536: the width lands near ~750px (legible), not shrunk to nothing.
    assert 700 <= img.width <= 800


def test_small_image_is_not_upscaled(tmp_path):
    src = tmp_path / "small.png"
    Image.new("RGB", (400, 600), (10, 10, 10)).save(src, format="PNG")

    img = _decode(_service()._image_for_vision(str(src)))
    assert img.size == (400, 600)


def test_missing_file_returns_none():
    assert _service()._image_for_vision("/no/such/file.png") is None
