#!/usr/bin/env python3
"""Run once to create the white logo for the app."""
from PIL import Image
import numpy as np
import os

src = "/mnt/user-data/uploads/LOGO_-__Navy_white_no_background.png"
dst = os.path.join(os.path.dirname(__file__), "logo_white.png")

img = Image.open(src).convert("RGB")
arr = np.array(img)

r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
black_mask = (r < 30) & (g < 30) & (b < 30)
logo_mask = ~black_mask

rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
rgba[logo_mask] = [255, 255, 255, 255]
rgba[black_mask] = [0, 0, 0, 0]

Image.fromarray(rgba, 'RGBA').save(dst)
print(f"White logo saved to {dst}")
EOF
