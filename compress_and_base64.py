#!/usr/bin/env python3
"""Compress the flowchart and output base64 data URI."""

import base64
from pathlib import Path
from PIL import Image

src = Path("C:/Users/Administrator/.kimi-code/files/f_VET1CN7GBJ7RD7QEN7SDYD8BNZ")
dst = Path("C:/Users/Administrator/.kimi-code/files/f_VET1CN7GBJ7RD7QEN7SDYD8BNZ_compressed.jpg")

img = Image.open(src)
# Convert RGBA to RGB with white background
if img.mode == "RGBA":
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    img = bg

# Resize to max width 1600
max_width = 1600
w, h = img.size
if w > max_width:
    ratio = max_width / w
    img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)

img.save(dst, "JPEG", quality=85, optimize=True)

# Generate base64 data URI
b64 = base64.b64encode(dst.read_bytes()).decode("ascii")
print(f"data:image/jpeg;base64,{b64}")
print(f"\nCompressed size: {dst.stat().st_size} bytes")
