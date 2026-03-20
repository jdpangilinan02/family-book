#!/usr/bin/env python3
"""Generate AI demo photos for Family Book using aikaline/sprite-mcp."""

import asyncio
import sys
import os
from pathlib import Path

# Add aikaline src to path
AIKALINE_ROOT = Path.home() / "Dropbox" / "MCP" / "aikaline"
sys.path.insert(0, str(AIKALINE_ROOT / "src"))

from sprite_mcp.tools.generate_sprite import generate_sprite
from sprite_mcp.backends.openrouter import OpenRouterBackend

OUTPUT_DIR = Path.home() / "Dropbox" / "Code" / "family-book" / "app" / "static" / "demo-photos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Use available image generation models
PHOTO_MODEL = "google/gemini-2.5-flash-image"
PORTRAIT_MODEL = "google/gemini-2.5-flash-image"


async def generate_one(backend, filename, description, width=800, height=600, style="hand-painted"):
    """Generate a single image with error handling."""
    output_path = str(OUTPUT_DIR / filename)
    if Path(output_path).exists():
        print(f"  ⏭️  {filename} already exists, skipping")
        return True
    
    print(f"  🎨 Generating {filename}...")
    try:
        result = await generate_sprite(
            description=description,
            style=style,
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
    print("=" * 70)
    print("🏠 Family Book Demo Photo Generator")
    print("=" * 70)
    print(f"Output: {OUTPUT_DIR}")
    print(f"Model: {PHOTO_MODEL}\n")

    backend = OpenRouterBackend()
    results = {}

    try:
        # ═══════════════════════════════════════════════════════
        # FAMILY MOMENT PHOTOS (for Moments feed)
        # ═══════════════════════════════════════════════════════
        print("\n📸 FAMILY MOMENT PHOTOS\n")

        moment_photos = [
            (
                "family-dinner.jpg",
                "A warm, candid photograph of a multi-generational family dinner. "
                "A large table with Mediterranean food, wine glasses, bread. "
                "Grandparents, parents, and young children around the table. "
                "Warm golden evening light from hanging lamps. A cozy dining room "
                "with terracotta walls. Everyone is laughing and talking. "
                "Photorealistic, natural, candid family moment. Shot on 35mm film look.",
                800, 600,
            ),
            (
                "first-day-school.jpg",
                "A heartwarming photograph of a 3-year-old boy on his first day of preschool. "
                "He wears a small backpack and stands confidently at the school entrance gate. "
                "His mother kneels beside him, smiling with tears in her eyes. "
                "Morning sunlight, a colorful school facade in Barcelona. "
                "Mediterranean architecture in background. Photorealistic, emotional, candid.",
                800, 600,
            ),
            (
                "birthday-celebration.jpg",
                "A joyful photograph of a child's birthday party. A 6-year-old girl "
                "blowing out candles on a spectacular three-tier rocket ship cake with "
                "a toy dinosaur on top. Other children around the table cheering. "
                "Colorful decorations, streamers, balloons. Indoor party with natural light. "
                "Photorealistic, happy, vibrant colors. Candid moment.",
                800, 600,
            ),
            (
                "beach-vacation.jpg",
                "A beautiful photograph of a family at the beach during golden hour. "
                "A young couple with two small children playing in the shallow waves "
                "on a Mediterranean beach. The father carries a toddler on his shoulders "
                "while the mother holds the hand of a 3-year-old running along the shore. "
                "Warm sunset light, turquoise water, sandy beach. Costa Brava, Spain. "
                "Photorealistic, warm, joyful. Wide angle shot.",
                800, 600,
            ),
            (
                "christmas-morning.jpg",
                "A cozy photograph of Christmas morning in a Barcelona apartment. "
                "A Christmas tree with warm lights, wrapping paper scattered on the floor. "
                "A young boy excitedly holding up a dinosaur fossil while his baby sister "
                "plays with a toy piano. Parents watching from the couch with coffee. "
                "Morning light through large windows. Warm, intimate, festive. "
                "Photorealistic, candid family moment.",
                800, 600,
            ),
            (
                "summer-reunion.jpg",
                "A large multigenerational family group photo outdoors on a sunny terrace "
                "in Barcelona. About 10-12 people of all ages, from an elderly grandmother "
                "to toddlers. Mixed ethnicities (European, Asian, Latin). Everyone smiling "
                "and hugging. Mediterranean rooftop with plants, string lights. "
                "Summer afternoon, golden warm light. Photorealistic, joyful, diverse.",
                800, 600,
            ),
            (
                "new-years-eve.jpg",
                "A family celebrating New Year's Eve in a Barcelona apartment. "
                "A couple and their two young children at a beautifully set table. "
                "A bowl of grapes (12 grapes Spanish tradition). Champagne glasses, "
                "a clock showing almost midnight. Warm candlelight, festive but intimate. "
                "The boy tries to eat grapes quickly. The baby reaches for a grape. "
                "Photorealistic, warm, festive.",
                800, 600,
            ),
            (
                "woodworking-chair.jpg",
                "A photograph of an older man (60s) in his woodworking workshop, "
                "proudly displaying a hand-crafted walnut rocking chair. The chair is "
                "beautiful with intricate joinery, no nails. Wood shavings on the floor, "
                "tools on the wall. Warm workshop lighting. Portland, Oregon garage workshop. "
                "The man wears a flannel shirt and has sawdust in his hair. "
                "Photorealistic, warm, craftsman portrait.",
                800, 600,
            ),
        ]

        for filename, desc, w, h in moment_photos:
            results[filename] = await generate_one(backend, filename, desc, w, h)

        # ═══════════════════════════════════════════════════════
        # PORTRAIT PHOTOS (for family member profiles)
        # ═══════════════════════════════════════════════════════
        print("\n👤 FAMILY MEMBER PORTRAITS\n")

        portrait_photos = [
            (
                "portrait-alex.jpg",
                "Professional headshot portrait of a man in his late 30s. "
                "Mixed heritage (Mexican-Irish), brown hair, friendly warm smile. "
                "Wearing a casual button-up shirt. Blurred Mediterranean cityscape "
                "background (Barcelona). Natural light, slightly warm tones. "
                "Photorealistic portrait photo, shallow depth of field.",
                400, 400,
            ),
            (
                "portrait-maria.jpg",
                "Professional headshot portrait of a woman in her mid-30s. "
                "Russian heritage, light brown hair, green eyes, elegant but warm smile. "
                "Wearing a simple blouse. Blurred interior design studio background. "
                "Soft natural light from a window. Photorealistic portrait, "
                "shallow depth of field.",
                400, 400,
            ),
            (
                "portrait-james.jpg",
                "Professional portrait of a man in his mid-60s. "
                "Mexican heritage, graying temples, strong kind face, weathered hands. "
                "Wearing a plaid flannel shirt. Background of a tidy home workshop. "
                "Warm afternoon light. Retired teacher energy. Photorealistic.",
                400, 400,
            ),
            (
                "portrait-linda.jpg",
                "Professional portrait of a woman in her early 60s. "
                "Irish heritage, auburn hair with some gray, bright blue eyes, "
                "nurse practitioner in casual clothes. Kind, competent expression. "
                "Background blurred living room with bookshelves. Warm light. "
                "Photorealistic portrait.",
                400, 400,
            ),
            (
                "portrait-sophie.jpg",
                "Professional portrait of a woman in her late 30s. "
                "Mixed heritage (Mexican-Irish), athletic build, sun-kissed skin. "
                "Marine biologist casual — wearing a fleece jacket. Background of "
                "Pacific Northwest water/mountains (Seattle). Natural outdoor light. "
                "Photorealistic portrait, warm and confident expression.",
                400, 400,
            ),
            (
                "portrait-yuki.jpg",
                "Portrait of an elderly Japanese-Russian woman in her 80s. "
                "Elegant, silver hair in a neat bun. Warm wise eyes, gentle smile. "
                "Wearing a traditional silk scarf and cardigan. Japanese home interior "
                "background with subtle traditional elements. Soft warm light. "
                "Photorealistic portrait, dignified matriarch.",
                400, 400,
            ),
            (
                "portrait-elena.jpg",
                "Portrait of an elderly Russian woman in her late 80s. "
                "Sharp intelligent eyes, silver hair, slight amused expression "
                "like she knows something you don't. Wearing reading glasses on a chain. "
                "Background of bookshelves filled with Russian literature. "
                "Warm interior light. Saint Petersburg apartment. Photorealistic.",
                400, 400,
            ),
            (
                "portrait-dmitri.jpg",
                "Professional portrait of a man in his mid-30s. "
                "Russian heritage, creative look — slightly longer hair, "
                "designer stubble, thoughtful expression. Wearing a dark turtleneck. "
                "Background of a Berlin art gallery or design studio. "
                "Modern dramatic lighting. Photorealistic portrait.",
                400, 400,
            ),
            (
                "portrait-leo.jpg",
                "Portrait of a happy 3-year-old boy with mixed heritage "
                "(Russian-Mexican-Irish). Curly brown hair, big brown eyes, "
                "mischievous smile. Wearing a striped t-shirt. Holding a toy dinosaur. "
                "Bright playroom background. Natural light, warm colors. "
                "Photorealistic child portrait, candid and joyful.",
                400, 400,
            ),
            (
                "portrait-rosa.jpg",
                "Portrait of an elderly Mexican woman in her early 90s. "
                "Beautiful wrinkled face full of character and warmth. Silver hair "
                "pulled back, dark kind eyes. Wearing a colorful embroidered blouse. "
                "Kitchen background with hanging dried herbs. Warm light. "
                "Portland home. The family matriarch. Photorealistic.",
                400, 400,
            ),
        ]

        for filename, desc, w, h in portrait_photos:
            results[filename] = await generate_one(backend, filename, desc, w, h)

    finally:
        await backend.close()

    # Summary
    print("\n" + "=" * 70)
    succeeded = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"📊 Results: {succeeded} succeeded, {failed} failed out of {len(results)} total")
    print(f"📁 Output: {OUTPUT_DIR}")
    
    # List generated files
    photos = sorted(OUTPUT_DIR.glob("*.jpg")) + sorted(OUTPUT_DIR.glob("*.png"))
    if photos:
        print(f"\n📸 Generated files:")
        for p in photos:
            print(f"   {p.name} ({p.stat().st_size:,} bytes)")
    
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
