#!/usr/bin/env python3
"""Generate the remaining failed demo photos with fixed prompts."""

import asyncio
import sys
import os
from pathlib import Path

AIKALINE_ROOT = Path.home() / "Dropbox" / "MCP" / "aikaline"
sys.path.insert(0, str(AIKALINE_ROOT / "src"))

from sprite_mcp.tools.generate_sprite import generate_sprite
from sprite_mcp.backends.openrouter import OpenRouterBackend

OUTPUT_DIR = Path.home() / "Dropbox" / "Code" / "family-book" / "app" / "static" / "demo-photos"
PHOTO_MODEL = "google/gemini-2.5-flash-image"


async def generate_one(backend, filename, description, width=800, height=600):
    """Generate a single image — NO style preset to avoid conflict with photorealistic prompts."""
    output_path = str(OUTPUT_DIR / filename)
    
    print(f"  🎨 Generating {filename}...")
    try:
        result = await generate_sprite(
            description=description,
            style=None,  # No style preset — let the prompt control everything
            width=width,
            height=height,
            background="white",
            model=PHOTO_MODEL,
            output_path=output_path,
            backend=backend,
        )
        size = Path(result['path']).stat().st_size
        print(f"  ✅ {filename} — {size:,} bytes ({result['width']}x{result['height']})")
        return True
    except Exception as e:
        print(f"  ❌ {filename} failed: {e}")
        return False


async def main():
    print("🔧 Generating remaining photos (fixed prompts)\n")
    
    backend = OpenRouterBackend()
    results = {}

    try:
        remaining = [
            (
                "beach-vacation.jpg",
                "A photograph of a family at the beach during golden hour. "
                "A young couple with two small children playing in the shallow waves "
                "on a Mediterranean beach. The father carries a toddler on his shoulders "
                "while the mother holds a 3-year-old's hand near the shore. "
                "Warm sunset light, turquoise water, sandy beach. "
                "Photograph style, warm, joyful, wide angle.",
                800, 600,
            ),
            (
                "woodworking-chair.jpg",
                "A photograph of a man in his 60s in a woodworking workshop, "
                "proudly standing next to a hand-crafted walnut rocking chair. "
                "The chair has beautiful intricate joinery. Wood shavings on the floor, "
                "tools hung on the wall. Warm workshop lighting from a window. "
                "The man wears a flannel shirt. Photograph style, warm tones.",
                800, 600,
            ),
            (
                "portrait-alex.jpg",
                "A portrait photograph of a man in his late 30s. "
                "Brown hair, friendly warm smile, slight tan. "
                "Wearing a casual button-up shirt. Blurred Mediterranean cityscape "
                "in the background. Natural daylight, warm tones. "
                "Portrait photograph, shallow depth of field.",
                400, 400,
            ),
            (
                "portrait-maria.jpg",
                "A portrait photograph of a woman in her mid-30s. "
                "Light brown hair, green eyes, warm elegant smile. "
                "Wearing a simple blouse. Soft natural window light. "
                "Blurred interior background. "
                "Portrait photograph, shallow depth of field.",
                400, 400,
            ),
            (
                "portrait-rosa.jpg",
                "A portrait photograph of an elderly Mexican woman in her early 90s. "
                "Beautiful weathered face full of warmth. Silver hair pulled back, "
                "dark kind eyes. Wearing a colorful embroidered traditional blouse. "
                "Warm natural light. Simple warm-toned background. "
                "Portrait photograph, respectful and dignified.",
                400, 400,
            ),
        ]

        for filename, desc, w, h in remaining:
            results[filename] = await generate_one(backend, filename, desc, w, h)

    finally:
        await backend.close()

    succeeded = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"\n📊 Results: {succeeded}/{len(results)} succeeded")
    
    # List all files in output dir
    photos = sorted(OUTPUT_DIR.glob("*.jpg")) + sorted(OUTPUT_DIR.glob("*.png"))
    print(f"\n📸 All demo photos ({len(photos)} total):")
    for p in photos:
        print(f"   {p.name} ({p.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
