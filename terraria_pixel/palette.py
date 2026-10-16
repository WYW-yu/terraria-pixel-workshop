"""原版放置贴图校准的材料调色板；喷漆缓存以白色顶点绘制。"""
from __future__ import annotations

from dataclasses import dataclass

from .calibrated_colors import TILE_COLORS, WALL_COLORS, MODEL_VERSION
from .color_model import mean_painted_color
from .material_library import catalog, placed_tables, actuated_tables, PLACED_MODEL, ACTUATED_MODEL, MAP_MODEL


BLOCKS: list[dict] = catalog()
WALLS: list[dict] = catalog(walls=True)

# 名称/ID 与小地图漆色；rgb 仅用于清单图例，不用于材质渲染。
ALL_PAINTS: list[dict] = [
    {"id": 0, "name": "No Paint",   "name_zh": "无喷漆", "rgb": (255, 255, 255)},
    {"id": 1, "name": "Red Paint",  "name_zh": "红漆",   "rgb": (255, 0, 0)},
    {"id": 2, "name": "Orange Paint", "name_zh": "橙漆", "rgb": (255, 127, 0)},
    {"id": 3, "name": "Yellow Paint", "name_zh": "黄漆", "rgb": (255, 255, 0)},
    {"id": 4, "name": "Lime Paint", "name_zh": "青柠漆", "rgb": (127, 255, 0)},
    {"id": 5, "name": "Green Paint", "name_zh": "绿漆",  "rgb": (0, 255, 0)},
    {"id": 6, "name": "Teal Paint", "name_zh": "蓝绿漆", "rgb": (0, 255, 127)},
    {"id": 7, "name": "Cyan Paint", "name_zh": "青漆",   "rgb": (0, 255, 255)},
    {"id": 8, "name": "Sky Blue Paint", "name_zh": "天蓝漆", "rgb": (0, 127, 255)},
    {"id": 9, "name": "Blue Paint", "name_zh": "蓝漆",   "rgb": (0, 0, 255)},
    {"id": 10, "name": "Purple Paint", "name_zh": "紫漆", "rgb": (127, 0, 255)},
    {"id": 11, "name": "Violet Paint", "name_zh": "紫罗兰漆", "rgb": (255, 0, 255)},
    {"id": 12, "name": "Pink Paint", "name_zh": "粉漆",  "rgb": (255, 0, 127)},
]
# 深色漆: id 13+i 与第 i+1 种标准色（红~粉共 12 种）**同色**（游戏数据表如此），
# 游戏内差异来自着色器 pass（深色版把非主通道基准压到 0.4m），由 color_model.py 复现。
for _i in range(12):
    base = ALL_PAINTS[1 + _i]
    ALL_PAINTS.append({
        "id": 13 + _i,
        "name": "Deep " + base["name"],
        "name_zh": "深" + base["name_zh"],
        "rgb": base["rgb"],          # 与普通漆同色（WorldGen.paintColor 实测数据）
    })
# 黑/白/灰/棕（id 25-28，MapColors.xml 真实值）
ALL_PAINTS += [
    {"id": 25, "name": "Black Paint", "name_zh": "黑漆", "rgb": (75, 75, 75)},
    {"id": 26, "name": "White Paint", "name_zh": "白漆", "rgb": (255, 255, 255)},
    {"id": 27, "name": "Gray Paint", "name_zh": "灰漆",  "rgb": (175, 175, 175)},
    {"id": 28, "name": "Brown Paint", "name_zh": "棕漆", "rgb": (255, 178, 125)},
    {"id": 29, "name": "Shadow Paint", "name_zh": "暗影漆", "rgb": (25, 25, 25)},
    {"id": 30, "name": "Negative Paint", "name_zh": "负漆", "rgb": (200, 200, 200)},
]

# 喷漆范围：无漆、深色漆(13-24)、黑白灰棕(25-28)、暗影及负漆(29-30)。
#   深色漆与普通漆漆色相同，但游戏里上色更暗更饱和（0.4m），按用户要求统一用深色漆。
#   普通漆(1-12) 仍保留在 ALL_PAINTS 里备查（改 USE_DEEP_PAINTS_ONLY=False 即可恢复）。
USE_DEEP_PAINTS_ONLY = True
PAINTS: list[dict] = (
    [p for p in ALL_PAINTS if p["id"] == 0 or 13 <= p["id"] <= 30]
    if USE_DEEP_PAINTS_ONLY else list(ALL_PAINTS)
)


@dataclass(frozen=True)
class Candidate:
    """一个颜色候选 = 方块 + 喷漆。"""
    block: dict
    paint: dict
    rgb: tuple[int, int, int]


def _candidate_rgb(block: dict, paint: dict) -> tuple[int, int, int]:
    """默认材质读取逐纹素校准表；自定义 RGB 材质按单色纹素计算。"""
    pid = paint["id"]
    if block.get('color_model') == ACTUATED_MODEL:
        return tuple(actuated_tables()[block['tile_id']][pid])
    if block.get("color_model") == MAP_MODEL:
        from .map_colors import map_painted_color
        return map_painted_color(block["rgb"], pid, wall="wall_id" in block)
    if block.get("color_model") == PLACED_MODEL:
        kind = "wall" if "wall_id" in block else "tile"
        ident = block[kind + "_id"]
        return tuple(placed_tables()[kind, ident][pid])
    if block.get("color_model") == MODEL_VERSION:
        table = WALL_COLORS if "wall_id" in block else TILE_COLORS
        ident = block.get("wall_id", block.get("tile_id"))
        if ident in table and 0 <= pid < len(table[ident]):
            return table[ident][pid]
    return mean_painted_color(block["rgb"], pid, wall='wall_id' in block)


class Palette:
    """由 BLOCKS × PAINTS 生成全部颜色候选。"""

    def __init__(self, blocks: list[dict] | None = None, paints: list[dict] | None = None):
        self.blocks = list(blocks) if blocks is not None else [b for b in BLOCKS if b["rgb"] is not None]
        self.paints = list(paints) if paints is not None else list(PAINTS)
        self._candidates: list[Candidate] = []
        for b in self.blocks:
            for p in self.paints:
                self._candidates.append(
                    Candidate(block=b, paint=p, rgb=_candidate_rgb(b, p))
                )

    @property
    def candidates(self) -> list[Candidate]:
        return self._candidates

    def candidate_rgb_array(self):
        import numpy as np
        if not hasattr(self, '_rgb_cache'):
            self._rgb_cache = np.asarray([c.rgb for c in self._candidates], dtype=np.uint8)
        return self._rgb_cache

    def matching_data(self):
        """逐纹素 Lab 的均值/方差；平方距离加方差等于逐纹素平均色差。"""
        if hasattr(self, '_matching_cache'):
            return self._matching_cache
        import numpy as np
        from .quantize import rgb_to_lab, CHROMA_WEIGHT
        labs = rgb_to_lab(self.candidate_rgb_array())
        costs = np.zeros(len(self.candidates))
        allowed = np.ones(len(self.candidates), dtype=bool)
        for i, c in enumerate(self.candidates):
            b, pid = c.block, c.paint['id']
            if b.get('color_model') not in (PLACED_MODEL, ACTUATED_MODEL):
                continue
            allowed[i] = b.get('auto_eligible', False)
            if 'placed_lab' in b and 'placed_variance' in b:
                labs[i] = b['placed_lab'][pid]
                costs[i] = np.dot(b['placed_variance'][pid], (1, CHROMA_WEIGHT, CHROMA_WEIGHT))
        from .material_rules import candidate_flags
        allowed &= candidate_flags(self)[0]
        if not allowed.any():
            raise ValueError('当前色库没有适合自动匹配的稳定素材，请手动选材。')
        self._matching_cache = labs, costs, allowed
        return self._matching_cache

    def describe(self, idx: int) -> str:
        c = self._candidates[idx]
        prefix = ("墙 · " if "wall_id" in c.block else "物块 · ") if c.block.get("color_model") == MAP_MODEL else ""
        if c.paint["id"] == 0:
            return prefix + c.block["name_zh"]
        return f'{prefix}{c.block["name_zh"]} + {c.paint["name_zh"]}'


def wall_palette() -> "Palette":
    """已校准背景墙 × 默认喷漆选项。"""
    return Palette(blocks=WALLS, paints=PAINTS)


def mixed_palette() -> "Palette":
    """混合版共用一套贴图匹配，候选包含允许的物块和背景墙。"""
    return Palette(blocks=catalog(walls=None, actuated=True), paints=PAINTS)


def map_palette(walls=None) -> "Palette":
    """地图版默认共用物块和背景墙；显式布尔参数供分库校验与旧数据兼容。"""
    return Palette(blocks=catalog(walls=walls, map_colors=True), paints=PAINTS)
