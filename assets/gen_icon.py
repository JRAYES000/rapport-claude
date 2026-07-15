"""Génère logo.ico (multi-résolutions, pour l'exe) et logo.png (256, pour le tray)
à partir de logo_source.png (logo École de Naturopathie & Sophrologie)."""
import os
from PIL import Image

here = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(here, "logo_source.png")
im = Image.open(src).convert("RGBA")
w, h = im.size

# Canvas carré transparent + petite marge (8%) pour ne pas coller aux bords
margin = int(max(w, h) * 0.08)
s = max(w, h) + 2 * margin
canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
canvas.paste(im, ((s - w) // 2, (s - h) // 2), im)

ico_path = os.path.join(here, "logo.ico")
png_path = os.path.join(here, "logo.png")
canvas.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                             (64, 64), (128, 128), (256, 256)])
canvas.resize((256, 256), Image.LANCZOS).save(png_path)
print("source:", im.size, "-> canvas:", canvas.size)
print("OK ico:", ico_path, os.path.getsize(ico_path), "octets")
print("OK png:", png_path, os.path.getsize(png_path), "octets")
