"""材料安全规则；ID 来自 Terraria 1.4.5.8 TileID.Sets 的实际数据。"""
import numpy as np
from .material_access import wall_replacement

# WorldGen.hardUpdateWorld 实际读取这三组传播源，而不是按物品名称判断。
SPREADS_CORRUPTION = frozenset((23, 661, 25, 112, 398, 400, 163, 32, 636, 24))
SPREADS_CRIMSON = frozenset((199, 662, 203, 234, 399, 401, 200, 352, 205, 201))
SPREADS_HALLOW = frozenset((109, 492, 117, 116, 402, 403, 164, 115, 110, 113))
SPREADING_TILES = SPREADS_CORRUPTION | SPREADS_CRIMSON | SPREADS_HALLOW
FALLING_TILES = frozenset((53, 234, 112, 116, 224, 123, 330, 331, 332, 333, 495))
# Main.tileCut：Projectile.CutTiles -> DelegateMethods.CutTiles 使用此标记。
CUTTABLE_TILES = frozenset((3,24,28,32,51,52,61,62,69,71,73,74,82,83,84,
    110,113,115,184,201,205,231,236,254,352,382,444,454,484,485,518,519,
    528,529,549,636,637,638,654,655,711))
WATER_FRAGILE_TILES = frozenset((3,20,24,27,73,201,80,110,529,530,590,595,615,637))
TOUCH_FRAGILE_TILES = frozenset((32,69,352,655))
TEMPORARY_TILES = frozenset((127,162,481,482,483,504))  # 临时冰块、破裂地牢砖、长笛盘蛇
FRAGILE_TILES = CUTTABLE_TILES | WATER_FRAGILE_TILES | TOUCH_FRAGILE_TILES | TEMPORARY_TILES
FALLING_EFFECT_TILES = frozenset((192,196,384,460,717,718,719))
UNAVAILABLE_TILES = frozenset((668,))  # 最土的块挖出的是宠物，不能作为物块重新放置
UNAVAILABLE_WALLS = frozenset((272,273,350))  # 两条未使用墙和不可破坏墙
FORBIDDEN_TILES = SPREADING_TILES | FALLING_TILES | FRAGILE_TILES | FALLING_EFFECT_TILES | UNAVAILABLE_TILES


def exclusion_reason(block):
    if 'wall_id' in block:
        wid = block['wall_id']
        if wid in UNAVAILABLE_WALLS:
            return '内部未使用或无法正常放置的特殊墙'
        replacement = wall_replacement(wid)
        if replacement is not None:
            return f'天然墙版本，请改用可放置的同名墙（墙 ID {replacement}）'
        return ''
    tid = block.get('tile_id')
    if tid in UNAVAILABLE_TILES:
        return '最土的块是宠物来源，不能作为物块重新放置'
    if tid == 504:
        return '长笛生成的临时盘蛇，不能作为永久建材'
    if tid in SPREADING_TILES:
        return '会传播腐化、猩红或神圣的物块'
    if tid in FALLING_TILES:
        return '重力物块'
    if tid == 127:
        return '临时冰块（ID 127），不能持久保存'
    if tid in FRAGILE_TILES:
        return '易被射弹、接触或环境破坏，或不能持久保存的素材'
    if tid in FALLING_EFFECT_TILES:
        return '具有下雨、降雪、落叶或其他下落特效的物块'
    return ''


def permitted(block):
    return not exclusion_reason(block)


def candidate_flags(palette):
    if not hasattr(palette, '_safety_flags'):
        blocks = [c.block for c in palette.candidates]
        palette._safety_flags = (
            np.array([permitted(b) for b in blocks], bool),
            np.array(['wall_id' not in b and b.get('tile_id') in FALLING_TILES for b in blocks], bool),
            # 墙、透明空格以及装饰性非实体素材不能作为重力方块的可靠支撑。
            np.array(['tile_id' in b and b['tile_id'] != 165 and b.get('auto_eligible', True)
                      for b in blocks], bool),
        )
    return palette._safety_flags


def nearest_permitted(rgb, palette, *, map_colors=False, non_falling=False):
    allowed, falling, _ = candidate_flags(palette)
    allowed = allowed.copy()
    if non_falling:
        allowed &= ~falling
    if map_colors:
        from .map_colors import nearest_rgb
        ids = np.flatnonzero(allowed)
        if not len(ids):
            raise ValueError('当前色库没有符合安全规则的材料。')
        if not hasattr(palette, '_safe_map_colors'):
            palette._safe_map_colors = {}
        if non_falling not in palette._safe_map_colors:
            palette._safe_map_colors[non_falling] = palette.candidate_rgb_array()[ids].astype(np.int32)
        return int(ids[nearest_rgb(rgb, palette._safe_map_colors[non_falling])])
    from .quantize import rgb_to_lab, CHROMA_WEIGHT
    labs, costs, stable = palette.matching_data()
    allowed &= stable
    if not allowed.any():
        raise ValueError('当前色库没有符合安全规则的稳定材料。')
    delta = labs - rgb_to_lab(np.asarray(rgb[:3]))
    distances = np.sum(delta * delta * (1, CHROMA_WEIGHT, CHROMA_WEIGHT), axis=1) + costs
    distances[~allowed] = np.inf
    return int(np.argmin(distances))


def repair_grid(grid, palette, rgb, *, map_colors=False, cancel=None, columns=None, copy=True):
    """仅替换违规格；全图禁用传播源、重力和易损/临时物块。"""
    grid = np.array(grid, dtype=np.int32, copy=True) if copy else np.asarray(grid)
    allowed, falling, support = candidate_flags(palette)
    if columns is None:
        columns = np.arange(grid.shape[1])
    else:
        columns = np.unique(columns)
    cache = {}

    def replace(y, x, non_falling):
        color = tuple(map(int, rgb[y, x, :3]))
        key = color, non_falling
        if key not in cache:
            cache[key] = nearest_permitted(color, palette, map_colors=map_colors, non_falling=non_falling)
        grid[y, x] = cache[key]

    for y in range(grid.shape[0] - 1, -1, -1):
        if cancel:
            cancel()
        row = grid[y, columns].copy()
        present = row >= 0
        invalid = present & ~allowed[np.maximum(row, 0)]
        for x in columns[invalid]:
            replace(y, x, False)
    return grid


def validate_grid(grid, palette):
    """旧草稿仍可打开，但不允许把违规材料写进图纸或世界。"""
    grid = np.asarray(grid)
    if grid.ndim != 2 or not grid.size or grid.min() < -1 or grid.max() >= len(palette.candidates):
        raise ValueError('作品含有无效的材料编号。')
    allowed, falling, support = candidate_flags(palette)
    present = grid >= 0
    safe_indices = np.maximum(grid, 0)
    invalid = present & ~allowed[safe_indices]
    if invalid.any():
        index = int(grid[invalid][0])
        reason = exclusion_reason(palette.candidates[index].block)
        raise ValueError(f'作品含有{reason}，请重新转换或替换后再导出。')
