"""Баннер поста об обновлении (вариант «Горн»): 1280x640, угольный фон с жаром и искрами, золотая рамка, номер версии.

Использование: python3 banner.py <версия> <файл.png>. Шрифты Cormorant (SIL OFL 1.1) - в fonts/ рядом.
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 640
FONTS = Path(__file__).resolve().parent / "fonts"
GOLD = (214, 172, 98)


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def ember_background():
    """Радиальный жар снизу по центру; считается в четверть размера и растягивается - градиент гладкий, а счёт быстрый."""
    w, h = W // 4, H // 4
    inner, outer = (150, 52, 14), (14, 11, 10)
    img = Image.new("RGB", (w, h), outer)
    px = img.load()
    cx, cy, radius = w / 2, h + 10, 230
    for y in range(h):
        for x in range(w):
            t = min(1.0, math.hypot(x - cx, (y - cy) * 1.15) / radius)
            t = t * t * (3 - 2 * t)
            px[x, y] = tuple(int(inner[i] + (outer[i] - inner[i]) * t) for i in range(3))
    return img.resize((W, H), Image.BICUBIC).convert("RGBA")


def sparks():
    """Искры гуще и ярче к низу; зерно фиксировано - баннеры разных версий отличаются только номером."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    rnd = random.Random(7)
    for _ in range(140):
        x = rnd.gauss(W / 2, 260)
        y = H - abs(rnd.gauss(0, 210))
        r = rnd.choice([1, 1, 1.5, 2, 2.5])
        alpha = int(255 * (y / H) ** 1.5)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 170 + rnd.randint(0, 60), 80, alpha))
    return layer


def centered(draw, y, text, fnt, fill, spacing=0):
    parts = list(text) if spacing else [text]
    widths = [draw.textlength(p, font=fnt) for p in parts]
    x = (W - sum(widths) - spacing * (len(parts) - 1)) / 2
    for part, w in zip(parts, widths):
        draw.text((x, y), part, font=fnt, fill=fill)
        x += w + spacing


def glow_text(base, y, text, fnt, fill, glow, blur, spacing=0):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    centered(ImageDraw.Draw(layer), y, text, fnt, glow, spacing)
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))
    centered(ImageDraw.Draw(base), y, text, fnt, fill, spacing)


def diamond(draw, cx, cy, r, fill):
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)


def frame(draw):
    draw.rectangle([28, 28, W - 29, H - 29], outline=GOLD + (150,), width=2)
    draw.rectangle([40, 40, W - 41, H - 41], outline=GOLD + (70,), width=1)
    for cx, cy in [(28, 28), (W - 29, 28), (28, H - 29), (W - 29, H - 29)]:
        diamond(draw, cx, cy, 10, GOLD)


def divider(draw, y, half):
    cx = W / 2
    draw.line([(cx - half, y), (cx - 22, y)], fill=GOLD, width=2)
    draw.line([(cx + 22, y), (cx + half, y)], fill=GOLD, width=2)
    diamond(draw, cx, y, 9, GOLD)
    diamond(draw, cx - half - 8, y, 4, GOLD)
    diamond(draw, cx + half + 8, y, 4, GOLD)


def render(version):
    img = ember_background()
    spark_layer = sparks()
    img.alpha_composite(spark_layer.filter(ImageFilter.GaussianBlur(0.6)))
    img.alpha_composite(spark_layer)
    frame(ImageDraw.Draw(img))
    glow_text(img, 150, "EXILE FORGE", font("CormorantSC-Bold.ttf", 64), (232, 200, 140), (255, 140, 40, 200), 10, spacing=14)
    divider(ImageDraw.Draw(img), 258, 260)
    centered(ImageDraw.Draw(img), 292, "Обновление", font("Cormorant-Variable.ttf", 60), (240, 226, 200))
    glow_text(img, 360, version, font("CormorantSC-Bold.ttf", 150), (255, 236, 196), (255, 120, 30, 230), 22)
    return img.convert("RGB")


if __name__ == "__main__":
    version, out = sys.argv[1], Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    render(version).save(out, optimize=True)
    print(f"banner: {out.name}")
