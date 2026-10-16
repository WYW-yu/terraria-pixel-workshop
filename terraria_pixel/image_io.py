"""图片加载、像素化（降采样）与预览图生成"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
Image.MAX_IMAGE_PIXELS = None  # 不以固定格数阻止用户的像素图片，实际容量取决于内存。


def load_image_pixels(path):
    """保留PNG/GIF/WebP等图片的真实Alpha；不透明图片保持RGB。"""
    with Image.open(path) as source:
        img = ImageOps.exif_transpose(source)
        mode = 'RGBA' if 'A' in img.getbands() or 'transparency' in img.info else 'RGB'
        return np.array(img.convert(mode), dtype=np.uint8)


def load_image_rgb(path: str | Path) -> np.ndarray:
    """读取图片并转为 RGB 的 uint8 数组 (H, W, 3)。"""
    with Image.open(path) as source:
        img = ImageOps.exif_transpose(source)
        if "A" in img.getbands() or "transparency" in img.info:
            rgba = img.convert("RGBA")
            canvas = Image.new("RGBA", rgba.size, "white")
            img = Image.alpha_composite(canvas, rgba).convert("RGB")
        else:
            img = img.convert("RGB")
        return np.array(img, dtype=np.uint8)


def image_size(path: str | Path) -> tuple[int, int]:
    """返回图片原始尺寸 (宽, 高)。"""
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).size


def detect_grid(rgb: np.ndarray, sample_rows: int = 200) -> int | None:
    """检测图片是否由"规则方格"组成（像素画网格），是则返回列数，否则 None。

    原理：像素画网格的每一格是纯色方块，格与格之间有整齐的"颜色突变边界"。
    沿水平方向扫描若干行，统计每个 x 位置发生颜色突变的行数占比；
    如果突变位置间距均匀（= 格子宽度），且格子宽度能整除图片宽度，
    就判定为规则网格，返回 图片宽 ÷ 格子宽 = 列数。

    返回 None 表示不像规则网格（普通照片/自由图），由调用方决定用默认宽度。
    """
    h, w = rgb.shape[:2]
    if h < 4 or w < 4:
        return None
    # 均匀采样若干行（降低计算量，同时覆盖全图）
    rows = np.linspace(0, h - 1, min(sample_rows, h)).astype(int)
    sub = rgb[rows]  # (R, W, 3)
    # 每个 x 位置：相邻像素是否"明显不同"（色差阈值，容忍 JPEG 压缩噪点）
    diff = np.abs(sub[:, 1:].astype(np.int32) - sub[:, :-1].astype(np.int32)).sum(axis=2)
    edge = diff > 60  # (R, W-1)
    # 突变占比：某列边界在多少采样行上同时出现
    frac = edge.mean(axis=0)  # (W-1,)
    # 边界位置：超过一半行都在这里突变 → 真实格线
    bounds = np.where(frac > 0.5)[0] + 1
    if bounds.size < 2:
        return None
    gaps = np.diff(bounds)
    # 格子宽度 = 间距的中位数；要求间距基本均匀（像素画格子是等宽的）
    g = np.median(gaps)
    if g < 1.5:
        return None
    spread = np.abs(gaps - g)
    if (spread <= max(1.0, g * 0.15)).mean() < 0.75:
        return None
    # 图片宽度应≈格子宽×列数（容差：最后一格可能贴边）
    cols = round(w / g)
    if cols < 2 or cols > 512:
        return None
    if abs(cols * g - w) / w > 0.25:
        return None
    return cols


def is_pixel_grid(rgb: np.ndarray) -> bool:
    """保守识别整数倍放大的纯色网格；完整验证，避免把照片误判成像素画。"""
    h, w = rgb.shape[:2]
    rows = rgb[np.linspace(0, h - 1, min(h, 64)).astype(int)]
    cols = rgb[:, np.linspace(0, w - 1, min(w, 64)).astype(int)]
    xb = np.flatnonzero(np.any(rows[:, 1:] != rows[:, :-1], axis=(0, 2))) + 1
    yb = np.flatnonzero(np.any(cols[1:] != cols[:-1], axis=(1, 2))) + 1
    gx = int(np.gcd.reduce(np.r_[xb, w]))
    gy = int(np.gcd.reduce(np.r_[yb, h]))
    if gx < 2 or gy < 2:
        return False
    reference = rgb[::gy, ::gx].repeat(gx, axis=1)
    for start in range(0, h, 128):
        if not np.array_equal(rgb[start:start + 128], reference[np.arange(start, min(start + 128, h)) // gy]):
            return False
    return True


def resolve_sampling(rgb: np.ndarray, width: int, height: int, sampling: str) -> str:
    if sampling not in {"auto", "nearest", "area", "edge"}:
        raise ValueError("sampling 必须是 auto / nearest / area / edge")
    if sampling == "auto":
        return "nearest" if (width >= rgb.shape[1] and height >= rgb.shape[0]) or is_pixel_grid(rgb) else "edge"
    return sampling


def pixelate(rgb: np.ndarray, width: int, height: int | None = None, *,
             sampling: str = "auto", detail: float = 0.4, contrast: float = 1.0,
             saturation: float = 1.0, gamma: float = 1.0, color_limit: int = 0) -> np.ndarray:
    """降采样 → 温和轮廓增强 → 调色 → 可选中位切分限色。

    auto 保留整数倍像素网格，普通图片先面积平均，抑制最近邻的抽样噪点。
    edge 只在有对比度的边缘增强，限制增量以减少锐化光晕。
    color_limit 限制输入颜色；实际建造颜色仍由 Terraria 材料库决定。
    """
    h, w = rgb.shape[:2]
    if height is None:
        height = max(1, round(h * width / w))
    if width < 1 or height < 1:
        raise ValueError("目标宽高必须 >= 1")
    if not (0 <= detail <= 1 and 0 <= contrast <= 2 and 0 <= saturation <= 2 and 0.2 <= gamma <= 3):
        raise ValueError("细节需为 0–1，对比度/饱和度为 0–2，gamma 为 0.2–3")
    if color_limit != 0 and not 2 <= color_limit <= 256:
        raise ValueError("颜色上限应为 0（不限）或 2–256")
    mode = resolve_sampling(rgb, width, height, sampling)
    img = Image.fromarray(rgb)
    img = img.resize((width, height), Image.Resampling.NEAREST if mode == "nearest" else Image.Resampling.BOX)
    alpha = np.asarray(img.getchannel('A')).copy() if img.mode == 'RGBA' else None
    img = img.convert('RGB')
    if mode == "edge" and detail:
        base = np.asarray(img, dtype=np.float32)
        blur = np.asarray(img.filter(ImageFilter.GaussianBlur(0.7)), dtype=np.float32)
        luminance = base @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        padded = np.pad(luminance, 1, mode="edge")
        gradient = np.maximum(np.abs(padded[1:-1, 2:] - padded[1:-1, :-2]),
                              np.abs(padded[2:, 1:-1] - padded[:-2, 1:-1]))
        mask = np.clip(gradient / 40.0, 0, 1)[..., None]
        change = np.clip((base - blur) * detail * mask, -12, 12)
        img = Image.fromarray(np.clip(np.rint(base + change), 0, 255).astype(np.uint8))
    if contrast != 1:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1:
        img = ImageEnhance.Color(img).enhance(saturation)
    if gamma != 1:
        table = np.rint((np.arange(256) / 255.0) ** (1.0 / gamma) * 255).astype(np.uint8).tolist()
        img = img.point(table * 3)
    if color_limit:
        img = img.quantize(colors=color_limit, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE).convert("RGB")
    values = np.asarray(img, dtype=np.uint8)
    return np.dstack((values, alpha)) if alpha is not None else values



