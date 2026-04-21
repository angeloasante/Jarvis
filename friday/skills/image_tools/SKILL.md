---
name: image-tools
description: Create, resize, compress, convert, and optimize images. Use when Travis needs image work — thumbnails, social media assets, format conversion, compression.
agents: [system_agent, code_agent, social_agent]
---

# Image Tools

Image manipulation via Python Pillow or ffmpeg. No external services needed.

## Format Guide

| Format | Best for | Notes |
|--------|----------|-------|
| WebP | Web, general purpose | Smallest size, modern browsers |
| JPEG | Photos, social media | Lossy, no transparency |
| PNG | Screenshots, UI, logos | Lossless, supports transparency |
| SVG | Icons, diagrams | Vector, infinitely scalable |
| AVIF | Web (next-gen) | Even smaller than WebP, less support |

## Resize Image

```python
from PIL import Image
img = Image.open("input.jpg")
img.thumbnail((800, 600))  # Max 800x600, keeps aspect ratio
img.save("resized.jpg", quality=85)
```

## Compress Image

```python
from PIL import Image
img = Image.open("input.jpg")
# JPEG compression
img.save("compressed.jpg", quality=60, optimize=True)
# WebP (even smaller)
img.save("compressed.webp", quality=70)
# PNG optimization
img.save("compressed.png", optimize=True)
```

## Convert Format

```python
from PIL import Image
img = Image.open("input.png")
img.convert("RGB").save("output.jpg", quality=85)  # PNG → JPEG
img.save("output.webp", quality=80)                  # PNG → WebP
```

## Crop Image

```python
from PIL import Image
img = Image.open("input.jpg")
# Crop box: (left, top, right, bottom)
cropped = img.crop((100, 100, 500, 400))
cropped.save("cropped.jpg")
```

## Create Thumbnail

```python
from PIL import Image
img = Image.open("input.jpg")
img.thumbnail((150, 150))
img.save("thumb.jpg")
```

## Social Media Sizes

| Platform | Size | Notes |
|----------|------|-------|
| Twitter/X post | 1200x675 | 16:9, JPEG/PNG |
| Twitter/X profile | 400x400 | Square |
| LinkedIn post | 1200x627 | |
| Instagram post | 1080x1080 | Square |
| Instagram story | 1080x1920 | 9:16 |
| YouTube thumbnail | 1280x720 | |
| OG/meta image | 1200x630 | For link previews |

## Add Text to Image

```python
from PIL import Image, ImageDraw, ImageFont
img = Image.open("input.jpg")
draw = ImageDraw.Draw(img)
draw.text((50, 50), "FRIDAY", fill="white")
img.save("with_text.jpg")
```

## Batch Processing (via ffmpeg)

```bash
# Convert all PNGs to WebP
for f in *.png; do ffmpeg -i "$f" "${f%.png}.webp"; done

# Resize all images to max 1200px width
for f in *.jpg; do ffmpeg -i "$f" -vf "scale=1200:-1" "resized_$f"; done
```

## Where to Save

Save to `~/Documents/friday_files/` unless specified.
For screenshots: `~/Downloads/friday_screenshots/`
