"""RGB/RGBA显示、透明材料与PNG网格导出共用函数。"""
import numpy as np
from PIL import Image, ImageDraw


def color_text(value):
    value = tuple(map(int, value))
    if len(value) == 4 and value[3] == 0:
        return '透明'
    text = '#%02X%02X%02X' % value[:3]
    return text + (f' · 不透明度 {value[3] / 255:.0%}' if len(value) == 4 and value[3] < 255 else '')


def material_pixels(grid, palette):
    colors = palette.candidate_rgb_array()[np.maximum(grid, 0)]
    if np.any(grid < 0):
        alpha = np.where(grid < 0, 0, 255).astype(np.uint8)
        colors = np.dstack((colors, alpha))
        colors[grid < 0, :3] = 0
    return colors


def png_image(pixels, *, grid=False, cell_size=12):
    image = Image.fromarray(pixels)
    if not grid:
        return image
    # 一像素的原尺寸无法同时保留颜色和格线；网格版以整数倍放大每格。
    step = max(4, int(cell_size))
    w, h = image.size
    image = image.resize((w * step, h * step), Image.Resampling.NEAREST).convert('RGBA')
    lines = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(lines)
    for x in range(0, image.width, step):
        draw.line((x, 0, x, image.height), fill=(0, 0, 0, 130))
        draw.line((x+1, 0, x+1, image.height), fill=(255, 255, 255, 100))
    for y in range(0, image.height, step):
        draw.line((0, y, image.width, y), fill=(0, 0, 0, 130))
        draw.line((0, y+1, image.width, y+1), fill=(255, 255, 255, 100))
    draw.rectangle((0, 0, image.width-1, image.height-1), outline=(0, 0, 0, 150))
    return Image.alpha_composite(image, lines)


def validate_schematic_size(width, height, scale=1):
    if width < 1 or height < 1 or scale < 1:
        raise ValueError('图纸宽高及每格大小必须大于0。')
    if width > 4096 or height > 4096 or width * height > 2_000_000:
        raise ValueError('泰拉图纸每边最多4096格，总像素格数最多200万；可继续预览、保存草稿或导出PNG。')
    if width * height * scale * scale > 20_000_000:
        raise ValueError('泰拉图纸建筑格数最多2000万；请缩小每格大小。PNG导出不受此限制。')
