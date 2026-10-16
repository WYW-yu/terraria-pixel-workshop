"""Terraria TileShader 的纹素变换；绘制顶点为白色，不乘小地图漆色表。"""
from __future__ import annotations

import numpy as np

# Red..Pink：0=M，1=中间值，2=低值。来自 12 个独立 shader pass。
ROLES = ((0, 2, 2), (0, 1, 2), (0, 0, 2), (1, 0, 2),
         (2, 0, 2), (2, 0, 1), (2, 0, 0), (2, 1, 0),
         (2, 2, 0), (1, 2, 0), (0, 2, 0), (0, 2, 1))


def paint_texels(rgb, paint_id: int, *, wall: bool = False):
    """输入/输出为 0..255 浮点 RGB。先逐纹素变换，再钳制到渲染目标范围。"""
    t = np.asarray(rgb, dtype=np.float64) / 255.0
    hi, lo = t.max(axis=-1), t.min(axis=-1)
    if paint_id in (0, 31):
        result = t
    elif 1 <= paint_id <= 24:
        low = lo * (0.4 if paint_id >= 13 else 1.0)
        values = np.stack((hi, (hi + low) * 0.5, low), axis=-1)
        result = values[..., ROLES[(paint_id - 1) % 12]]
    elif paint_id in (25, 26, 27, 29):
        if paint_id == 25:
            value = (hi + lo) * 0.15
        elif paint_id == 26:
            value = (0.7 * hi + 0.3 * lo) * (2 - (hi + lo) * 0.5)
        elif paint_id == 27:
            value = (hi + lo) * 0.5
        else:
            value = (hi + lo) * 0.025
        result = np.repeat(value[..., None], 3, axis=-1)
    elif paint_id == 28:
        result = hi[..., None] * np.array((1.0, 0.7, 0.49))
    elif paint_id == 30:
        # 游戏的墙负漆使用 pass 43，物块用 pass 42；全黑纹素均保持黑色。
        result = np.where(hi[..., None] > 0, 0.75 - 2 * t if wall else 1 - t, t)
    else:
        raise ValueError(f"不支持的喷漆 ID: {paint_id}")
    return np.clip(result * 255, 0, 255)


def mean_painted_color(rgb, paint_id: int, *, wall: bool = False):
    """模拟 8 位喷漆缓存，白漆的非线性公式不能在平均纹素上计算。"""
    texels = np.rint(paint_texels(rgb, paint_id, wall=wall))
    return tuple(int(v) for v in np.rint(texels.reshape(-1, 3).mean(axis=0)))
