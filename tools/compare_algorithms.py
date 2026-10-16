"""生成可重现的合成素材对比图，不读取个人照片。"""
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terraria_pixel.image_io import pixelate
from terraria_pixel.quantize import match_to_palette, rgb_to_lab
from terraria_pixel.palette import Palette

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / ".tmp" / "algorithm-comparison"
out.mkdir(parents=True, exist_ok=True)
font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 22)
small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
canvas = Image.new("RGB", (1304, 860), "#10191b")
draw = ImageDraw.Draw(canvas)
draw.text((28, 18), "v4.1 算法对比 · 相同 128 格宽度 / 相同 Terraria 调色板", font=font, fill="#dcece4")
draw.text((28, 54), "合成风景含渐变、斜线与细密纹理；下方独立展示双色调色板的感知明度混合。", font=small, fill="#8ea5a3")
w, h = 1024, 768
y, x = np.mgrid[:h, :w]
t = y / h
rgb = np.stack([165 - t * 60, 210 - t * 55, 230 - t * 55], axis=-1)
scene = Image.fromarray(rgb.astype(np.uint8))
pen = ImageDraw.Draw(scene)
pen.ellipse((760, 70, 850, 160), fill="#ffdfa4")
pen.polygon([(0, 490), (240, 170), (510, 490)], fill="#789997")
pen.polygon([(280, 520), (625, 130), (1024, 530)], fill="#416e78")
pen.polygon([(555, 210), (625, 130), (709, 220), (650, 195), (615, 230)], fill="#e4ece1")
pen.rectangle((0, 490, 1023, 767), fill="#54836a")
pen.polygon([(320, 768), (540, 490), (595, 490), (650, 768)], fill="#6ba5b4")
pen.rectangle((160, 520, 365, 675), fill="#c29b70")
pen.polygon([(130, 525), (260, 408), (394, 525)], fill="#8a5549")
pen.rectangle((210, 585, 260, 675), fill="#433b3b")
pen.rectangle((290, 565, 340, 620), fill="#ffdc9a")
pen.line((0, 360, 1024, 190), fill="#333c42", width=5)
rgb = np.asarray(scene).astype(np.float32).copy()
# 细纹类似远处草地和屋顶瓦片，最近邻会依采样相位产生明显偏差。
mask = (y > 490) & ((x < 130) | (x > 680))
texture = (np.sin(x * np.pi / 2) + np.cos(y * np.pi / 2)) * 22
rgb[mask] += texture[mask, None]
rgb = np.clip(rgb, 0, 255).astype(np.uint8)
Image.fromarray(rgb).save(out / "合成测试原图.png")
palette = Palette().candidate_rgb_array()
grids = []
for col, (title, sampling, dither, limit) in enumerate((
    ("旧算法 · 最近邻", "nearest", "none", 0),
    ("新默认 · 抗锯齿 + 轮廓", "auto", "none", 0),
    ("可选风格 · 16 色 + Bayer", "edge", "bayer", 16))):
    start = time.perf_counter()
    processed = pixelate(rgb, 128, sampling=sampling, color_limit=limit)
    grid = match_to_palette(processed, palette, dither=dither)
    elapsed = time.perf_counter() - start
    print(f"{sampling}/{dither}: {elapsed:.3f}s, {len(np.unique(grid))} combinations")
    result = Image.fromarray(palette[grid]).resize((400, 300), Image.Resampling.NEAREST)
    left = 28 + col * 424
    draw.text((left, 103), title, font=font, fill="#a6e9b8")
    canvas.paste(result, (left, 145))
    draw.text((left, 458), "实际游戏材料平均色预览", font=small, fill="#8ea5a3")
    grids.append(grid)
draw.text((28, 510), "双色压力测试 · RGB 128 灰色 → 黑 / 白 · 抖动强度 1.0", font=font, fill="#dcece4")
grey = np.full((32, 128, 3), 128, dtype=np.uint8)
bw = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
target = rgb_to_lab(grey)[..., 0].mean()
for col, (title, mode) in enumerate((("关闭", "none"), ("Bayer 4×4", "bayer"), ("Floyd–Steinberg", "floyd"))):
    grid = match_to_palette(grey, bw, dither=mode, strength=1)
    mean = rgb_to_lab(bw[grid])[..., 0].mean()
    left = 28 + col * 424
    draw.text((left, 559), title, font=font, fill="#a6e9b8")
    canvas.paste(Image.fromarray(bw[grid]).resize((400, 100), Image.Resampling.NEAREST), (left, 600))
    draw.text((left, 716), f"平均 Lab 明度 {mean:.1f} / 目标 {target:.1f}", font=small, fill="#8ea5a3")
draw.text((28, 787), "抖动用空间混色表达过渡，会增加颗粒感；照片默认不开启，原像素画自动保留纯色色块。", font=small, fill="#8ea5a3")
canvas.save(out / "算法效果对比.png")
print(out / "算法效果对比.png")
