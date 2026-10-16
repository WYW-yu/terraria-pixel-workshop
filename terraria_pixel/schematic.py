"""TEditSch 图纸文件生成（二进制格式，TEdit 4/5 原生）。

格式（V4，版本标记 = 世界版本 + 10000，逐字段对照 TEdit 源码）:
  [名字: 7bit长度 + UTF-8]
  [版本+10000: u32]
  [tileFrameImportant: Int16 长度 + 位数组]
  [宽: u32][高: u32]
  [逐列 RLE 压缩的方块数据]
  [箱子: Int16 数量=0][牌子: Int16 数量=0][实体: 1 字节数量=0]
  [验证名字][验证版本: u32][验证宽: u32][验证高: u32]
"""
from __future__ import annotations

import struct
from pathlib import Path

from .tedsch_frames import TILE_FRAME_IMPORTANT
from .pixels import validate_schematic_size

VERSION = 319          # 世界版本（与用户 TEdit 一致）
FRAMES = TILE_FRAME_IMPORTANT
MAX_TILE_ID = 0xFFFF   # 不裁剪
MAX_WALL_ID = 0xFFFF
ICE_BY_ROD = 127       # 不参与序列化的特殊方块

# ---- 夜明涂料（发光涂层 / Illuminant Coating / fullbright）----
# 游戏里 WorldGen.paintCoatTile(x,y,1) 置 Tile.fullbrightBlock，paintCoatWall 置 fullbrightWall。
# 1.4.4+ 格子 header 是链式 h1→h2→h3→h4（每字节 bit0 = "还有下一个 header 字节"）：
#   h1: bit1 有方块 / bit2 有墙 / bit3-4 液体 / bit5 方块ID>255 / bit6-7 RLE
#   h2: bit1-3 红蓝绿电线 / bit4-6 坡度
#   h3: bit1 致动器 / bit2 已致动 / bit3 有方块漆 / bit4 有墙漆 / bit5 黄电线 / bit6 墙ID>255 / bit7 微光液体
#   h4: bit1 方块回声涂料 / bit2 墙回声涂料 / bit3 方块夜明涂料 / bit4 墙夜明涂料
# （格式对照开源实现 terraria-world-file / src/section/WorldTiles.ts 的 FLAG_4 定义）
COAT_TILE_BIT = 0b0000_1000      # h4 bit3 = 方块夜明涂料（fullbrightBlock）
COAT_WALL_BIT = 0b0001_0000      # h4 bit4 = 墙夜明涂料（fullbrightWall）


def _write_string(buf: bytearray, s: str) -> None:
    data = s.encode("utf-8")
    length = len(data)
    while length >= 0x80:
        buf.append((length & 0x7F) | 0x80)
        length >>= 7
    buf.append(length)
    buf += data


def _write_bit_array(buf: bytearray, values: list[bool]) -> None:
    buf += struct.pack("<h", len(values))
    cur = 0
    mask = 1
    for v in values:
        if v:
            cur |= mask
        if mask != 128:
            mask <<= 1
        else:
            buf.append(cur)
            cur = 0
            mask = 1
    if mask != 1:
        buf.append(cur)


def serialize_tile(active: bool, type_id: int, u: int, v: int,
                   tile_color: int, wall: int, wall_color: int,
                   illuminant_tile: bool = False,
                   illuminant_wall: bool = False, *, inactive: bool = False) -> bytes:
    """按 Terraria 世界方块格式序列化一个格子（1.4.4 / 版本>=269 规则）。

    illuminant_tile / illuminant_wall = 该格方块/墙是否加"夜明涂料"（发光涂层）。
    """
    buf = bytearray(16)
    data_idx = 4
    h1 = h2 = h3 = h4 = 0

    if active and type_id <= MAX_TILE_ID and type_id != ICE_BY_ROD:
        h1 |= 0b0000_0010
        buf[data_idx] = type_id & 0xFF
        data_idx += 1
        if type_id > 255:
            buf[data_idx] = (type_id >> 8) & 0xFF
            data_idx += 1
            h1 |= 0b0010_0000
        framed = FRAMES[type_id] if type_id < len(FRAMES) else True
        if framed:
            buf[data_idx] = u & 0xFF
            buf[data_idx + 1] = (u >> 8) & 0xFF
            buf[data_idx + 2] = v & 0xFF
            buf[data_idx + 3] = (v >> 8) & 0xFF
            data_idx += 4
        if illuminant_tile:
            h4 |= COAT_TILE_BIT          # 夜明涂料：方块满亮度（h4 bit3）
        if inactive:
            h3 |= 0b0000_0100            # 已虚化；保留物块与绘制，不添加致动器/电线。
        if tile_color != 0 and tile_color != 31:
            h3 |= 0b0000_1000
            buf[data_idx] = tile_color
            data_idx += 1

    if wall != 0 and wall <= MAX_WALL_ID:
        h1 |= 0b0000_0100
        buf[data_idx] = wall & 0xFF
        data_idx += 1
        if illuminant_wall:
            h4 |= COAT_WALL_BIT          # 夜明涂料：墙满亮度（h4 bit4）
        if wall_color != 0 and wall_color != 31:
            h3 |= 0b0001_0000
            buf[data_idx] = wall_color
            data_idx += 1

    # 不附加液体、电路、坡度或致动器物品。

    if wall > 255:
        h3 |= 0b0100_0000
        buf[data_idx] = (wall >> 8) & 0xFF
        data_idx += 1

    header_idx = 3
    if h4 != 0:
        h3 |= 0b0000_0001
        buf[header_idx] = h4
        header_idx -= 1
    if h3 != 0:
        h2 |= 0b0000_0001
        buf[header_idx] = h3
        header_idx -= 1
    if h2 != 0:
        h1 |= 0b0000_0001
        buf[header_idx] = h2
        header_idx -= 1
    buf[header_idx] = h1
    return bytes(buf[header_idx:data_idx])


def _cell_at(cells: list, x: int, y: int, scale: int, w: int):
    px, py = x // scale, y // scale
    return cells[py * w + px]


def write_tedsch(grid, palette, path: str | Path, *, name: str,
                 scale: int = 1, walls_only: bool = False,
                 coating: bool = True, progress=None, cancel=None, actuated: bool = True) -> Path:
    """把候选索引网格写成 TEditSch 图纸。

    walls_only=False: 每格放方块（tile + tileColor 喷漆）
    walls_only=True : 每格只放墙（wall + wallColor 喷漆）
    coating=True    : 每一格再加"夜明涂料"（Illuminant Coating / 发光涂层），
                      游戏内材质满亮度显示，不照亮周围（TEdit 里能看到该格带涂料）
    """
    path = Path(path)
    if scale < 1:
        raise ValueError("scale 必须 >= 1")
    h, w = grid.shape
    from .material_rules import validate_grid
    validate_grid(grid, palette)
    validate_schematic_size(w, h, scale)
    size_x, size_y = w * scale, h * scale

    # 按候选缓存二进制记录，不再为全图每个像素建立 Python 元组。
    import numpy as np
    records = {}
    no_rle = set()
    for idx in np.unique(grid):
        if idx == -1:
            records[-1] = serialize_tile(False, 0, 0, 0, 0, 0, 0)
            continue
        cand = palette.candidates[int(idx)]
        base, pid = cand.block, cand.paint["id"]
        if walls_only or "wall_id" in base:
            cell = (False, 0, 0, 0, 0, base.get("wall_id", 0), pid, False, coating)
        else:
            tid = base.get("tile_id", 0)
            if tid == ICE_BY_ROD:
                raise ValueError("选中的材料含临时冰块（ID 127），游戏无法持久保存。请在编辑器替换该材料，或仅保存作品记录。")
            cell = (True, tid, 0, 0, pid, 0, 0, coating, False)
            if tid in (520, 423):
                no_rle.add(int(idx))
        records[int(idx)] = serialize_tile(*cell, inactive=actuated and cell[0])

    buf = bytearray()
    _write_string(buf, name)
    buf += struct.pack("<I", VERSION + 10000)
    _write_bit_array(buf, FRAMES)
    buf += struct.pack("<II", size_x, size_y)

    # 逐列 RLE 序列化（x 外循环，y 内循环；纵向连续相同格子合并）
    for x in range(size_x):
        if cancel:
            cancel()
        if progress:
            progress(x / size_x)
        y = 0
        while y < size_y:
            idx = int(grid[y // scale, x // scale])
            cur = records[idx]
            rec = bytearray(cur)
            rle = 0
            ny = y + 1
            while ny < size_y and rle < 32767 and idx not in no_rle \
                    and records[int(grid[ny // scale, x // scale])] == cur:
                rle += 1
                ny += 1
            if rle > 0:
                rec.append(rle & 0xFF)
                if rle <= 255:
                    rec[0] |= 0b0100_0000
                else:
                    rec[0] |= 0b1000_0000
                    rec.append((rle >> 8) & 0xFF)
            buf += rec
            y = ny

    # 箱子 / 牌子 / 实体（都为空）
    buf += struct.pack("<h", 0)  # chests 数量 (Int16)
    buf += struct.pack("<h", 0)  # signs 数量 (Int16)
    buf += struct.pack("<I", 0)  # tile entities 数量 (Int32)

    # 验证尾部
    _write_string(buf, name)
    buf += struct.pack("<I", VERSION)
    buf += struct.pack("<II", size_x, size_y)

    path.write_bytes(buf)
    if progress:
        progress(1.0)
    return path
