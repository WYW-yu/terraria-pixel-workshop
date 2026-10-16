"""应用内材料数量统计。"""
from collections import Counter
from .palette import Palette
from .material_access import item_id_for

def _stats(grid, palette: Palette, scale: int = 1):
    """统计 (base, paint) → 数量；返回 rows（组合明细）、block_rows（按基底汇总）、paint_rows（按喷漆汇总）。"""
    counter = Counter(int(v) for v in grid.ravel())
    stats: dict[tuple, int] = Counter()
    for idx, count in counter.items():
        if idx < 0:
            continue
        count *= scale * scale
        c = palette.candidates[idx]
        bid = c.block.get("wall_id", c.block.get("tile_id"))
        key = (c.block["name_zh"], c.block["name"], bid,
               item_id_for(c.block), tuple(c.block["rgb"]), c.paint["name_zh"],
               c.paint["name"], c.paint["id"])
        stats[key] += count

    rows = sorted(stats.items(), key=lambda kv: -kv[1])
    by_block: dict[tuple, dict] = {}
    for (zh, en, bid, iid, rgb, pzh, pen, pid), count in stats.items():
        bk = (zh, en, bid, iid, rgb)
        if bk not in by_block:
            by_block[bk] = {"total": 0, "paints": []}
        by_block[bk]["total"] += count
        if pzh != "无喷漆":
            by_block[bk]["paints"].append((pzh, pen, pid, count))
    block_rows = sorted(by_block.items(), key=lambda kv: -kv[1]["total"])

    # 按喷漆汇总：每种漆的总刷漆块数（不区分刷在哪种墙上）
    by_paint: dict[tuple, int] = Counter()
    for (zh, en, bid, iid, rgb, pzh, pen, pid), count in stats.items():
        if pzh != "无喷漆":
            by_paint[(pzh, pen, pid)] += count
    paint_rows = sorted(by_paint.items(), key=lambda kv: -kv[1])
    return rows, block_rows, paint_rows

