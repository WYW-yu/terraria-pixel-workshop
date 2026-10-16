"""像素画编辑：数据层（不含界面），供编辑窗口与测试共用。

色库规则：
- 像素画（材料匹配前的原色）不受限制，直接改 RGB；
- 混合版色库来自「允许的物块和背景墙 × 喷漆」；
- 背景墙版色库来自「背景墙 × 喷漆」。
材料版上色时按生成流程同一套 Lab 加权距离吸附到最近候选，保证编辑结果仍是可搭建的材料。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .palette import Palette
from .pixels import material_pixels

TARGET_PIXEL = "pixel"
TARGET_FINE = "fine"
TARGET_WALL = "wall"
TARGET_MAP = "map"

TARGETS = (TARGET_PIXEL, TARGET_FINE, TARGET_WALL, TARGET_MAP)
MATERIAL_TARGETS = (TARGET_FINE, TARGET_WALL, TARGET_MAP)
TARGET_LABELS = {
    TARGET_PIXEL: "像素画（色库不限）",
    TARGET_FINE: "混合版（物块和背景墙）",
    TARGET_WALL: "背景墙版（色库＝背景墙）",
    TARGET_MAP: "地图版（物块和背景墙地图色）",
}
UNDO_LIMIT = 200
UNDO_BYTES = 64 * 1024 * 1024


def rgb_tuple(values) -> tuple[int, int, int]:
    return tuple(map(int, values))


@dataclass
class EditCanvas:
    """一份结果里的某一版，拉进内存里编辑。"""

    rgb: np.ndarray                                # (H, W, 3) uint8，画面颜色
    target: str = TARGET_PIXEL
    indices: np.ndarray | None = None              # (H, W) int32，材料索引（材料版）
    palette: Palette | None = None                 # 材料版的候选来源
    _undo: list = field(default_factory=list, repr=False)
    _redo: list = field(default_factory=list, repr=False)
    _changed: bool = field(default=False, repr=False)
    _cand_cache: np.ndarray | None = field(default=None, repr=False)
    _lab_cache: np.ndarray | None = field(default=None, repr=False)
    _orig_rgb: np.ndarray | None = field(default=None, repr=False)
    _orig_indices: np.ndarray | None = field(default=None, repr=False)

    # ---------- 构造 ----------

    def __post_init__(self):
        self.rgb = np.array(self.rgb, dtype=np.uint8, order="C", copy=True)
        if self.rgb.ndim != 3 or self.rgb.shape[2] not in (3, 4) or not all(self.rgb.shape[:2]):
            raise ValueError("像素数据必须是RGB或RGBA数组。")
        if self.target not in TARGETS:
            raise ValueError(f"未知的编辑对象：{self.target}")
        if self.target == TARGET_PIXEL:
            if self.indices is not None or self.palette is not None:
                raise ValueError("像素画的色库不限，不应带材料数据。")
        else:
            if self.indices is None or self.palette is None:
                raise ValueError("材料版必须有材料索引和候选色库。")
            self.indices = np.array(self.indices, dtype=np.int32, order="C", copy=True)
            if self.indices.shape != self.rgb.shape[:2]:
                raise ValueError("材料索引与像素尺寸不一致。")
            if self.indices.min() < -1 or self.indices.max() >= len(self.palette.candidates):
                raise ValueError("材料索引超出色库范围。")
        self._orig_rgb = self.rgb.copy()
        self._orig_indices = None if self.indices is None else self.indices.copy()
        self._saved_rgb = self.rgb.copy()
        self._saved_indices = None if self.indices is None else self.indices.copy()
        self._colors_cache = None
        self._stroke = None

    @classmethod
    def blank(cls, width: int, height: int, color=(255, 255, 255)) -> "EditCanvas":
        """新建一块空白像素画布（色库不限，用于从零创作）。"""
        if int(width) < 1 or int(height) < 1:
            raise ValueError("画布宽高必须大于0。")
        rgb = np.empty((int(height), int(width), len(color)), dtype=np.uint8)
        rgb[:, :] = tuple(int(min(255, max(0, v))) for v in color)
        return cls(rgb=rgb, target=TARGET_PIXEL)

    @classmethod
    def from_result(cls, result, target: str) -> "EditCanvas":
        """按版本从 pipeline.Result 取数据；缺对应数据时抛 ValueError。"""
        if target == TARGET_PIXEL:
            if getattr(result, "processed_rgb", None) is None:
                raise ValueError("当前结果没有像素画数据，无法编辑。")
            return cls(rgb=np.array(result.processed_rgb, dtype=np.uint8, copy=True), target=target)
        if target not in MATERIAL_TARGETS:
            raise ValueError(f"未知的编辑对象：{target}")
        grid, palette = {
            TARGET_FINE: (result.grid, result.palette),
            TARGET_WALL: (result.grid_wall, result.palette_wall),
            TARGET_MAP: (result.grid_map, result.palette_map),
        }[target]
        if grid is None or palette is None:
            raise ValueError("当前结果没有这一版的材料数据，无法编辑。")
        indices = np.array(grid, dtype=np.int32, copy=True)
        rgb = np.ascontiguousarray(material_pixels(indices, palette), dtype=np.uint8)
        return cls(rgb=rgb, target=target, indices=indices, palette=palette)

    # ---------- 只读信息 ----------

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def is_material(self) -> bool:
        return self.target != TARGET_PIXEL

    @property
    def dirty(self) -> bool:
        return self._changed

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def candidates(self) -> np.ndarray | None:
        if not self.is_material:
            return None
        if self._cand_cache is None:
            self._cand_cache = np.ascontiguousarray(self.palette.candidate_rgb_array(), dtype=np.uint8)
        return self._cand_cache

    @property
    def labels(self) -> list[str]:
        if not self.is_material:
            return []
        if not hasattr(self, "_labels_cache"):
            self._labels_cache = [self.palette.describe(i) for i in range(len(self.palette.candidates))]
        return self._labels_cache

    def label_of(self, index: int) -> str:
        if not self.is_material:
            return ""
        return '透明（不放材料）' if index == -1 else self.palette.describe(int(index))

    def color_at(self, x: int, y: int) -> tuple[int, int, int]:
        self._check(x, y)
        return rgb_tuple(self.rgb[y, x])

    def index_at(self, x: int, y: int) -> int | None:
        if not self.is_material:
            return None
        self._check(x, y)
        return int(self.indices[y, x])

    def value_at(self, x: int, y: int):
        """材料版返回索引，像素画返回 RGB 元组。"""
        return self.index_at(x, y) if self.is_material else self.color_at(x, y)

    def used_colors(self) -> list[tuple[int, int, int]]:
        """这一版当前用到的颜色（按出现次数从多到少）。"""
        if self._colors_cache is None:
            colors, counts = np.unique(self.rgb.reshape(-1, self.rgb.shape[2]), axis=0, return_counts=True)
            order = np.argsort(-counts, kind="stable")
            self._colors_cache = [tuple(map(int, v)) for v in colors[order]]
        return self._colors_cache

    def nearest_index(self, rgb) -> int:
        """在候选色库里找最接近的材料，用与生成流程一致的 Lab 加权距离。"""
        if not self.is_material:
            raise ValueError("像素画的色库不限，不需要匹配材料。")
        from .material_rules import nearest_permitted
        return nearest_permitted(rgb, self.palette, map_colors=self.target in (TARGET_MAP))

    # ---------- 编辑 ----------

    def set_cell(self, x: int, y: int, rgb=None, index: int | None = None) -> bool:
        """改一格；材料版不传 index 时按 rgb 吸附到最近材料。返回是否真的改了。"""
        self._check(x, y)
        value_rgb, value_index = self._resolve(rgb, index)
        return self._commit(np.array([y]), np.array([x]), value_rgb, value_index) > 0

    def fill(self, x: int, y: int, rgb=None, index: int | None = None, bounds=None) -> int:
        """从 (x, y) 起把同值的四邻域连通区域整个换掉（扫描线填充），返回改动的格数。"""
        self._check(x, y)
        value_rgb, value_index = self._resolve(rgb, index)
        if self.value_at(x, y) == (value_index if self.is_material else value_rgb):
            return 0
        mask = self._region_mask(x, y, bounds=bounds)
        ys, xs = np.nonzero(mask)
        return self._commit(ys, xs, value_rgb, value_index)

    def fill_rectangle(self, bounds, rgb=None, index: int | None = None) -> int:
        """按当前色填满矩形，保留透明/材料语义，整次操作可一步撤销。"""
        x0, y0, x1, y1 = bounds
        x0, x1 = max(0, x0), min(self.width - 1, x1)
        y0, y1 = max(0, y0), min(self.height - 1, y1)
        if x0 > x1 or y0 > y1:
            return 0
        value_rgb, value_index = self._resolve(rgb, index)
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        return self._commit(ys.ravel(), xs.ravel(), value_rgb, value_index)

    def brush(self, x: int, y: int, size=1, rgb=None, index: int | None = None, bounds=None) -> int:
        """方形像素画笔，宽度按像素格计；笔触裁切到画布与选区内。"""
        self._check(x, y)
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 64:
            raise ValueError('画笔粗细应为1–64格。')
        left, top = x - (size - 1) // 2, y - (size - 1) // 2
        area = (left, top, left + size - 1, top + size - 1)
        if bounds is not None:
            area = (max(area[0], bounds[0]), max(area[1], bounds[1]),
                    min(area[2], bounds[2]), min(area[3], bounds[3]))
        return self.fill_rectangle(area, rgb=rgb, index=index)

    def replace_color(self, old_rgb, rgb=None, index: int | None = None) -> int:
        """把整张图里某个颜色一次性替换（像素画常用）。"""
        value_rgb, value_index = self._resolve(rgb, index)
        if self.rgb.shape[2] == 4 and len(old_rgb) == 3:
            old_rgb = tuple(old_rgb) + (255,)
        mask = np.all(self.rgb == np.asarray(old_rgb, dtype=np.uint8), axis=-1)
        ys, xs = np.nonzero(mask)
        return self._commit(ys, xs, value_rgb, value_index)

    def reset(self) -> int:
        """回到打开编辑窗口时的状态，可撤销。"""
        mask = np.any(self.rgb != self._orig_rgb, axis=-1)
        if self._orig_indices is not None:
            mask |= self.indices != self._orig_indices
        ys, xs = np.nonzero(mask)
        if not len(ys):
            return 0
        changed = self._commit(ys, xs, self._orig_rgb[ys, xs],
                               None if self._orig_indices is None else self._orig_indices[ys, xs])
        self._changed = self._touched()
        return changed

    def undo(self) -> int:
        if not self._undo:
            return 0
        step = self._undo.pop()
        self._write(step, use_prev=True)
        self._redo.append(step)
        self._changed = self._touched()
        return len(step[0])

    def redo(self) -> int:
        if not self._redo:
            return 0
        step = self._redo.pop()
        self._write(step, use_prev=False)
        self._undo.append(step)
        self._changed = self._touched()
        return len(step[0])

    def mark_applied(self):
        """记录已应用/导出的状态，保留撤销历史和初始重置目标。"""
        self._saved_rgb = self.rgb.copy()
        self._saved_indices = None if self.indices is None else self.indices.copy()
        self._changed = False

    def begin_stroke(self):
        self._stroke = []

    def end_stroke(self):
        steps, self._stroke = self._stroke, None
        if not steps:
            return
        cells = {}
        for ys, xs, prev, prev_idx, new, new_idx in steps:
            for i, (y, x) in enumerate(zip(ys, xs)):
                key = (int(y), int(x))
                if key not in cells:
                    cells[key] = [prev[i], None if prev_idx is None else prev_idx[i], new[i], None if new_idx is None else new_idx[i]]
                else:
                    cells[key][2:] = [new[i], None if new_idx is None else new_idx[i]]
        keys = list(cells)
        values = list(cells.values())
        step = (np.array([k[0] for k in keys]), np.array([k[1] for k in keys]),
                np.array([v[0] for v in values]), None if self.indices is None else np.array([v[1] for v in values]),
                np.array([v[2] for v in values]), None if self.indices is None else np.array([v[3] for v in values]))
        self._remember(step)

    def _remember(self, step):
        self._undo.append(step)
        total = sum(a.nbytes for s in self._undo for a in s if a is not None)
        while len(self._undo) > 1 and (len(self._undo) > UNDO_LIMIT or total > UNDO_BYTES):
            total -= sum(a.nbytes for a in self._undo.pop(0) if a is not None)

    def to_array(self) -> np.ndarray:
        """当前画面的 RGB 数组副本（创作完成后送进转换流程用）。"""
        return np.array(self.rgb, dtype=np.uint8, copy=True)

    def apply_to(self, result) -> None:
        """把编辑结果写回 pipeline.Result（调用方负责提示保存）。"""
        if self.target == TARGET_PIXEL:
            if not np.array_equal(result.processed_rgb, self.rgb):
                result.processing = dict(result.processing, pixels_confirmed=False,
                                         materials_stale=result.grid is not None)
            result.processed_rgb = np.array(self.rgb, dtype=np.uint8, copy=True)
            return
        grid = np.array(self.indices, dtype=np.int32, copy=True)
        if self.target == TARGET_FINE:
            result.grid = grid
        elif self.target == TARGET_WALL:
            result.grid_wall = grid
        elif self.target == TARGET_MAP:
            result.grid_map = grid

    # ---------- 内部 ----------

    def _check(self, x: int, y: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"坐标超出画布：({x}, {y})，画布 {self.width} × {self.height}")

    def _resolve(self, rgb, index):
        if (rgb is not None and len(rgb) == 4 and rgb[3] < 255) or index == -1:
            self._ensure_alpha()
        if (rgb is not None and len(rgb) == 4 and rgb[3] == 0) or index == -1:
            return (0, 0, 0, 0), -1 if self.is_material else None
        if self.is_material:
            idx = int(index) if index is not None else self.nearest_index(rgb if rgb is not None else (0, 0, 0))
            if not 0 <= idx < len(self.palette.candidates):
                raise ValueError(f"材料序号超出色库范围：{idx}")
            from .material_rules import exclusion_reason
            reason = exclusion_reason(self.palette.candidates[idx].block)
            if reason:
                raise ValueError(f'不能使用{reason}。')
            color = rgb_tuple(self.candidates[idx])
            return color + (255,) if self.rgb.shape[2] == 4 else color, idx
        if rgb is None:
            raise ValueError("像素画需要给定 RGB 颜色。")
        color = tuple(int(min(255, max(0, v))) for v in rgb)
        if self.rgb.shape[2] == 4 and len(color) == 3:
            color += (255,)
        return color, None

    def _ensure_alpha(self):
        if self.rgb.shape[2] == 4:
            return
        def rgba(array):
            return np.concatenate((array, np.full((*array.shape[:-1], 1), 255, np.uint8)), axis=-1)
        self.rgb, self._orig_rgb, self._saved_rgb = map(rgba, (self.rgb, self._orig_rgb, self._saved_rgb))
        for steps in (self._undo, self._redo, self._stroke or []):
            for i, step in enumerate(steps):
                y, x, prev, pi, new, ni = step
                steps[i] = y, x, rgba(prev), pi, rgba(new), ni

    def _region_mask(self, x: int, y: int, bounds=None) -> np.ndarray:
        """扫描线洪水填充，返回与起点同值的连通区域掩码。"""
        if self.is_material:
            same = self.indices == self.indices[y, x]
        elif self.rgb.shape[2] == 4 and self.rgb[y, x, 3] == 0:
            same = self.rgb[..., 3] == 0
        else:
            same = np.all(self.rgb == self.rgb[y, x], axis=-1)
        if bounds is not None:
            x0, y0, x1, y1 = bounds
            same[:y0, :] = False
            same[y1 + 1:, :] = False
            same[:, :x0] = False
            same[:, x1 + 1:] = False
        mask = np.zeros((self.height, self.width), dtype=bool)
        stack = [(x, y)]
        width = self.width
        while stack:
            sx, sy = stack.pop()
            if mask[sy, sx] or not same[sy, sx]:
                continue
            x0 = sx
            while x0 - 1 >= 0 and same[sy, x0 - 1] and not mask[sy, x0 - 1]:
                x0 -= 1
            x1 = sx
            while x1 + 1 < width and same[sy, x1 + 1] and not mask[sy, x1 + 1]:
                x1 += 1
            mask[sy, x0:x1 + 1] = True
            for ny in (sy - 1, sy + 1):
                if not 0 <= ny < self.height:
                    continue
                segment = same[ny, x0:x1 + 1] & ~mask[ny, x0:x1 + 1]
                if not segment.any():
                    continue
                edges = np.diff(np.concatenate(([0], segment.view(np.int8), [0])))
                for start in np.nonzero(edges == 1)[0]:
                    stack.append((int(x0 + start), ny))
        return mask

    def _as_rgb(self, value, count: int) -> np.ndarray:
        arr = np.asarray(value, dtype=np.uint8)
        return np.broadcast_to(arr, (count, self.rgb.shape[2])) if arr.ndim == 1 else arr

    def _commit(self, ys, xs, new_rgb, new_index) -> int:
        """写入若干格并记一步撤销；返回真正变化的格数。"""
        if not len(ys):
            return 0
        ys = np.asarray(ys); xs = np.asarray(xs)
        prev_rgb = self.rgb[ys, xs]
        prev_index = None if self.indices is None else self.indices[ys, xs]
        rgb_full = self._as_rgb(new_rgb, len(ys))
        index_full = None
        if self.indices is not None and new_index is not None:
            arr = np.asarray(new_index, dtype=np.int32)
            index_full = np.broadcast_to(arr, (len(ys),)) if arr.ndim == 0 else arr
            from .material_rules import repair_grid
            proposed = self.indices.copy()
            proposed[ys, xs] = index_full
            colors = self.rgb.copy()
            colors[ys, xs] = rgb_full
            repaired = repair_grid(proposed, self.palette, colors,
                                   map_colors=self.target in (TARGET_MAP),
                                   columns=xs, copy=False)
            extra_y, extra_x = np.nonzero((repaired != self.indices) & (repaired >= 0))
            # 自动换掉最底行/失去支撑的重力素材；与本次操作共用一次撤销。
            if len(extra_y):
                proposed_rgb = self.candidates[repaired[extra_y, extra_x]]
                if self.rgb.shape[2] == 4:
                    proposed_rgb = np.column_stack((proposed_rgb, np.full(len(extra_y), 255, np.uint8)))
                colors[extra_y, extra_x] = proposed_rgb
            ys, xs = np.nonzero(repaired != self.indices)
            index_full = repaired[ys, xs]
            rgb_full = colors[ys, xs]
            prev_rgb = self.rgb[ys, xs]
            prev_index = self.indices[ys, xs]
        if self.is_material:
            keep = index_full != prev_index
        else:
            keep = np.any(prev_rgb != rgb_full, axis=1)
        if not keep.any():
            return 0
        step = (ys[keep], xs[keep], prev_rgb[keep].copy(),
                None if prev_index is None else prev_index[keep].copy(),
                rgb_full[keep].copy(),
                None if index_full is None else index_full[keep].copy())
        self._write(step, use_prev=False)
        if self._stroke is not None:
            self._stroke.append(step)
        else:
            self._remember(step)
        self._redo.clear()
        self._changed = True
        self._colors_cache = None
        return int(keep.sum())

    def _write(self, step, *, use_prev: bool) -> None:
        ys, xs, prev_rgb, prev_index, new_rgb, new_index = step
        self.rgb[ys, xs] = prev_rgb if use_prev else new_rgb
        self._colors_cache = None
        if self.indices is not None:
            index = prev_index if use_prev else new_index
            if index is not None:
                self.indices[ys, xs] = index

    def _touched(self) -> bool:
        if not np.array_equal(self.rgb, self._saved_rgb):
            return True
        return self._saved_indices is not None and not np.array_equal(self.indices, self._saved_indices)
