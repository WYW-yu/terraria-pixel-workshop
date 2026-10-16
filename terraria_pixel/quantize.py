"""颜色匹配：把像素网格的每个像素匹配到最接近的（方块, 喷漆）组合。

用 Lab 颜色空间（更接近人眼感知）做最近邻搜索，numpy 向量化 + 分块控制内存。

色度加权（CHROMA_WEIGHT）：普通 CIELAB 距离里亮度差和色度差权重相同，
结果常常把"淡粉/肉色"匹配成同样亮的灰白（ΔL 小、但 a/b（色度）差很多）——
预览就变灰、发冷。这里把 a、b 的权重放大，让"色相/色度"更重要：
  距离² = ΔL² + CHROMA_WEIGHT × (Δa² + Δb²)
中性目标（a≈b≈0）仍然会被匹配到中性候选，不受影响。
"""
from __future__ import annotations

import numpy as np

# 色度权重：1.0 = 标准 CIELAB；越大越"保色相、允许亮度差一些"。
# 画布库扩充到 154 面墙后，暖色本身就有很近的候选（如蓝王朝墙 210,158,117），
# 所以权重只要轻微（1.3）——早期用 2.5 会把淡粉推向很暗的红棕墙。
CHROMA_WEIGHT = 1.3


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255) -> CIELAB。rgb 形状 (..., 3)。"""
    rgb = np.asarray(rgb, dtype=np.float64)
    r, g, b = rgb[..., 0] / 255.0, rgb[..., 1] / 255.0, rgb[..., 2] / 255.0

    def _lin(c: np.ndarray) -> np.ndarray:
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

    r, g, b = _lin(r), _lin(g), _lin(b)

    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    x /= 0.95047
    z /= 1.08883

    def _f(t: np.ndarray) -> np.ndarray:
        delta = 6.0 / 29.0
        return np.where(t > delta ** 3, np.cbrt(t), t / (3.0 * delta ** 2) + 4.0 / 29.0)

    fx, fy, fz = _f(x), _f(y), _f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    bb = 200.0 * (fy - fz)
    return np.stack([L, a, bb], axis=-1)


def match_to_palette(pixel_grid: np.ndarray, candidate_rgb: np.ndarray,
                     chunk: int = 4096, *, progress=None, cancel=None,
                     dither: str = "none", strength: float = 0.75,
                     candidate_lab=None, candidate_penalty=None) -> np.ndarray:
    """为每个像素找到最接近的颜色候选。

    pixel_grid: uint8 (H, W, 3)
    candidate_rgb: (C, 3) 每个候选的 RGB（0-255）
    返回 int32 (H, W)，值为候选索引。
    """
    if dither not in {"none", "bayer", "floyd"} or not 0 <= strength <= 1:
        raise ValueError("抖动模式需为 none / bayer / floyd，强度需为 0–1")
    if dither != "none" and strength:
        return _match_dithered(pixel_grid, candidate_rgb, dither, strength, chunk, progress, cancel,
                               candidate_lab, candidate_penalty)
    h, w = pixel_grid.shape[:2]
    # 同一 RGB 只匹配一次；像素画中大面积重复色不再重复搜索。
    colors, inverse = np.unique(pixel_grid.reshape(-1, 3), axis=0, return_inverse=True)
    lab_px = rgb_to_lab(colors)
    lab_c = rgb_to_lab(np.asarray(candidate_rgb, dtype=np.float64)) if candidate_lab is None else np.asarray(candidate_lab)
    n_cand = len(lab_c)
    if not n_cand:
        raise ValueError("调色板不能为空")
    # 每个二维临时数组限制在约 16 MiB，避免原 P×C×3 数组的大内存开销。
    chunk = max(1, min(chunk, (16 * 1024 * 1024) // (8 * n_cand)))
    out = np.empty(len(colors), dtype=np.int32)
    for s in range(0, len(colors), chunk):
        if cancel:
            cancel()
        e = min(s + chunk, len(colors))
        sq = np.zeros((e - s, n_cand), dtype=np.float64)
        for channel, weight in enumerate((1.0, CHROMA_WEIGHT, CHROMA_WEIGHT)):
            diff = lab_px[s:e, None, channel] - lab_c[None, :, channel]
            np.square(diff, out=diff)
            diff *= weight
            sq += diff
        if candidate_penalty is not None:
            sq += np.asarray(candidate_penalty)[None, :]
        out[s:e] = np.argmin(sq, axis=1)
        if progress:
            progress(e / len(colors))
    return out[inverse].reshape(h, w)


def _match_dithered(rgb, candidates, mode, strength, chunk, progress, cancel, labs=None, penalties=None):
    """直接输出真实材料索引；去除同色候选，避免抖动退化为同色切换。

    Bayer 将颜色投影到最近两色连线上，按 4×4 阈值混合。
    Floyd–Steinberg 在加权 Lab 空间蛇形扫描扩散误差，减少方向条纹。
    """
    candidates = np.asarray(candidates)
    costs = np.zeros(len(candidates)) if penalties is None else np.asarray(penalties)
    order = np.argsort(costs, kind='stable')
    unique, first = np.unique(candidates[order], axis=0, return_index=True)
    original = order[first]
    costs = costs[original]
    if not len(unique):
        raise ValueError("调色板不能为空")
    weights = np.sqrt([1.0, CHROMA_WEIGHT, CHROMA_WEIGHT])
    palette_lab = (rgb_to_lab(unique) if labs is None else np.asarray(labs)[original]) * weights
    h, w = rgb.shape[:2]
    if mode == "floyd":
        work = rgb_to_lab(rgb) * weights
        out = np.empty((h, w), dtype=np.int32)
        for y in range(h):
            if cancel:
                cancel()
            direction = 1 if y % 2 == 0 else -1
            for x in (range(w) if direction == 1 else range(w - 1, -1, -1)):
                current = np.clip(work[y, x], [0, -128 * weights[1], -128 * weights[2]],
                                  [100, 127 * weights[1], 127 * weights[2]])
                delta = palette_lab - current
                index = np.argmin(np.einsum("ij,ij->i", delta, delta) + costs)
                out[y, x] = original[index]
                error = (current - palette_lab[index]) * strength
                nx = x + direction
                if 0 <= nx < w:
                    work[y, nx] += error * (7 / 16)
                if y + 1 < h:
                    if 0 <= x - direction < w:
                        work[y + 1, x - direction] += error * (3 / 16)
                    work[y + 1, x] += error * (5 / 16)
                    if 0 <= nx < w:
                        work[y + 1, nx] += error * (1 / 16)
            if progress:
                progress((y + 1) / h)
        return out

    colors, inverse = np.unique(rgb.reshape(-1, 3), axis=0, return_inverse=True)
    source = rgb_to_lab(colors) * weights
    first = np.empty(len(colors), dtype=np.int32)
    second = np.empty_like(first)
    ratio = np.zeros(len(colors))
    chunk = max(1, min(chunk, (16 * 1024 * 1024) // (8 * len(unique))))
    for start in range(0, len(colors), chunk):
        if cancel:
            cancel()
        end = min(start + chunk, len(colors))
        distances = np.zeros((end - start, len(unique)))
        for c in range(3):
            distances += (source[start:end, None, c] - palette_lab[None, :, c]) ** 2
        distances += costs[None, :]
        rows = np.arange(end - start)
        a = distances.argmin(axis=1)
        distances[rows, a] = np.inf
        b = distances.argmin(axis=1)
        vector = palette_lab[b] - palette_lab[a]
        numerator = (np.sum((source[start:end] - palette_lab[a]) * vector, axis=1)
                     - (costs[b] - costs[a]) * 0.5)
        denominator = np.sum(vector * vector, axis=1)
        fraction = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0)
        first[start:end], second[start:end] = a, b
        ratio[start:end] = np.clip(fraction, 0, 1) * strength
        if progress:
            progress(end / len(colors))
    bayer = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16
    threshold = bayer[np.arange(h)[:, None] % 4, np.arange(w)[None, :] % 4]
    choose_second = threshold < ratio[inverse].reshape(h, w)
    return original[np.where(choose_second, second[inverse].reshape(h, w),
                              first[inverse].reshape(h, w))].astype(np.int32)
