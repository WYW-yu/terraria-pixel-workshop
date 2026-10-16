"""将已有材料网格放进 Terraria 世界，保留世界的其余数据。

使用“替换 Tiles 段并平移段指针”流程；不调用外部 DLL，
不重新匹配颜色、不重建箱子/NPC等段，不覆盖输入世界。
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import tempfile

import numpy as np

from .formats import ConversionCancelled


MAX_FILE_BYTES = 256 * 1024 * 1024
MIN_VERSION, MAX_VERSION = 269, 326


@dataclass(frozen=True)
class WorldInfo:
    name: str
    world_id: int
    version: int
    width: int
    height: int
    pointers: tuple[int, ...]
    frames: tuple[bool, ...]


@dataclass
class WorldDocument:
    path: Path
    data: bytes
    info: WorldInfo
    columns: tuple[int, ...]
    digest: bytes
    overview: np.ndarray | None = None


def _string(data, pos, limit):
    size = 0
    for shift in range(0, 35, 7):
        if pos >= limit:
            raise ValueError('世界文件的文字数据不完整。')
        byte = data[pos]
        pos += 1
        size |= (byte & 127) << shift
        if byte < 128:
            if size > 1024 * 1024 or pos + size > limit:
                raise ValueError('世界文件的文字长度不正确。')
            try:
                return data[pos:pos + size].decode('utf-8'), pos + size
            except UnicodeError as exc:
                raise ValueError('世界文件的文字编码不正确。') from exc
    raise ValueError('世界文件的文字长度不正确。')


def read_info(data: bytes) -> WorldInfo:
    if len(data) < 32 or data[4:12] != b'relogic\x02':
        raise ValueError('这不是支持的 Terraria .wld 世界文件。')
    version, = struct.unpack_from('<i', data)
    if not MIN_VERSION <= version <= MAX_VERSION:
        raise ValueError(f'暂不支持这个世界版本（{version}），支持版本 {MIN_VERSION}–{MAX_VERSION}，即 1.4.4–1.4.5 的对应存档。')
    count, = struct.unpack_from('<h', data, 24)
    if not 11 <= count <= 32 or 28 + count * 4 > len(data):
        raise ValueError('世界文件的分段表不完整。')
    pointers = struct.unpack_from('<' + 'i' * count, data, 26)
    frame_pos = 26 + count * 4
    frame_count, = struct.unpack_from('<h', data, frame_pos)
    frame_end = frame_pos + 2 + (frame_count + 7) // 8
    if not 1 <= frame_count <= 32767 or frame_end != pointers[0]:
        raise ValueError('世界文件的物块帧表不完整。')
    if not all(frame_end <= a <= b < len(data) for a, b in zip(pointers, pointers[1:])):
        raise ValueError('世界文件的分段位置不正确。')
    frames = tuple(bool(data[frame_pos + 2 + i // 8] & (1 << (i % 8))) for i in range(frame_count))
    pos, end = pointers[0], pointers[1]
    name, pos = _string(data, pos, end)
    _, pos = _string(data, pos, end)  # seed
    pos += 8 + 16                    # generator version / GUID
    if pos + 28 > end:
        raise ValueError('世界文件的基本信息不完整。')
    world_id, = struct.unpack_from('<i', data, pos)
    height, width = struct.unpack_from('<ii', data, pos + 20)
    if not (1 <= width <= 32767 and 1 <= height <= 32767 and width * height <= 100_000_000):
        raise ValueError('世界尺寸不正确或超出支持范围。')
    pos = pointers[-1]
    if data[pos] != 1:
        raise ValueError('世界文件的末尾校验标记不正确。')
    footer_name, pos = _string(data, pos + 1, len(data))
    if pos + 4 != len(data) or footer_name != name or struct.unpack_from('<i', data, pos)[0] != world_id:
        raise ValueError('世界文件的名称或编号校验失败。')
    return WorldInfo(name, world_id, version, width, height, pointers, frames)


def _run(data, pos, end, frames):
    """返回记录的正文末尾、下条偏移、长度及示意图所需材料字段。"""
    try:
        h1 = data[pos]
        pos += 1
        h2 = h3 = h4 = 0
        if h1 & 1:
            h2 = data[pos]
            pos += 1
            if h2 & 1:
                h3 = data[pos]
                pos += 1
                if h3 & 1:
                    h4 = data[pos]
                    pos += 1
        tile, wall, paint, wall_paint, liquid = -1, 0, 0, 0, 0
        if h1 & 2:
            tile = data[pos]
            pos += 1
            if h1 & 32:
                tile |= data[pos] << 8
                pos += 1
            if tile >= len(frames):
                raise ValueError('世界中有超出帧表范围的物块。')
            if frames[tile]:
                pos += 4
            if h3 & 8:
                paint = data[pos]
                pos += 1
        if h1 & 4:
            wall = data[pos]
            pos += 1
            if h3 & 16:
                wall_paint = data[pos]
                pos += 1
        if h1 & 24:
            liquid = 4 if h3 & 128 else (h1 & 24) >> 3
            pos += 1
        if h3 & 64:
            wall |= data[pos] << 8
            pos += 1
        body_end = pos
        code = h1 >> 6
        repeat = 0
        if code == 1:
            repeat = data[pos]
            pos += 1
        elif code >= 2:
            repeat, = struct.unpack_from('<h', data, pos)
            pos += 2
        if repeat < 0 or pos > end:
            raise ValueError('世界的方块压缩数据不完整。')
        return body_end, pos, repeat + 1, tile, wall, paint, wall_paint, liquid
    except (IndexError, struct.error) as exc:
        raise ValueError('世界的方块数据被截断。') from exc


def _check(cancelled):
    if cancelled and cancelled():
        raise ConversionCancelled()


def load_world(path, *, overview=True, progress=None, cancelled=None):
    path = Path(path).resolve()
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('世界文件超过 256 MB，暂不支持。')
    _check(cancelled)
    data = path.read_bytes()
    info = read_info(data)
    preview = None
    sample_columns = {}
    if overview:
        from .palette import map_palette
        colors = [{(c.block.get('tile_id', c.block.get('wall_id')), c.paint['id']): c.rgb
                   for c in map_palette(walls=walls).candidates} for walls in (False, True)]
        factor = min(1, 3000 / info.width, 1200 / info.height)
        pw, ph = max(1, round(info.width * factor)), max(1, round(info.height * factor))
        preview = np.full((ph, pw, 3), (24, 33, 51), np.uint8)
        sample_columns = dict(zip(np.linspace(0, info.width - 1, pw, dtype=int), range(pw)))
        rows = np.linspace(0, info.height - 1, ph, dtype=int)
    pos, end = info.pointers[1:3]
    columns = [pos]
    for x in range(info.width):
        _check(cancelled)
        y = row = 0
        px = sample_columns.get(x)
        while y < info.height:
            _, pos, count, tile, wall, paint, wall_paint, liquid = _run(data, pos, end, info.frames)
            next_y = y + count
            if next_y > info.height:
                raise ValueError('世界方块的压缩长度越过了列边界。')
            if px is not None:
                stop = int(np.searchsorted(rows, next_y))
                if stop > row:
                    color = (colors[0].get((tile, paint), (110, 114, 125)) if tile >= 0 else
                             ((36, 115, 196), (230, 89, 31), (195, 152, 38), (164, 109, 222))[liquid - 1] if liquid else
                             colors[1].get((wall, wall_paint), (65, 70, 85)) if wall else (24, 33, 51))
                    preview[row:stop, px] = color
                    row = stop
            y = next_y
        columns.append(pos)
        if progress and (x % 32 == 0 or x == info.width - 1):
            progress(round((x + 1) * 100 / info.width), '读取世界地形')
    if pos != end:
        raise ValueError('世界的方块段长度不匹配，未修改任何文件。')
    _check(cancelled)
    return WorldDocument(path, data, info, tuple(columns), hashlib.sha256(data).digest(), preview)


def _emit(buf, body, count, no_rle=False):
    while count:
        take = 1 if no_rle else min(count, 32768)
        repeat = take - 1
        if repeat:
            buf.append(body[0] | (64 if repeat <= 255 else 128))
            buf.extend(body[1:])
            buf.extend(struct.pack('<B' if repeat <= 255 else '<h', repeat))
        else:
            buf.extend(body)
        count -= take


def _rewrite_column(document, x, grid, records, left, top, scale):
    data, info = document.data, document.info
    pos, end = document.columns[x:x + 2]
    bottom = top + grid.shape[0] * scale
    column = (x - left) // scale
    buf = bytearray()
    pending, pending_count, pending_no_rle = None, 0, False

    def append(body, count, no_rle):
        nonlocal pending, pending_count, pending_no_rle
        if pending == body and pending_no_rle == no_rle:
            pending_count += count
        else:
            if pending is not None:
                _emit(buf, pending, pending_count, pending_no_rle)
            pending, pending_count, pending_no_rle = body, count, no_rle

    y = 0
    while y < info.height:
        start = pos
        body_end, pos, count, tile, *_ = _run(data, pos, end, info.frames)
        body = bytes([data[start] & 63]) + data[start + 1:body_end]
        run_end = y + count
        while y < run_end:
            if y < top:
                next_y = min(run_end, top)
                replacement = None
            elif y >= bottom:
                next_y = run_end
                replacement = None
            else:
                row = (y - top) // scale
                next_y = min(run_end, top + (row + 1) * scale)
                replacement = records.get(int(grid[row, column]))
            if replacement is None:
                append(body, next_y - y, tile in (423, 520))
            else:
                new_body, no_rle = replacement
                if tile >= 0 and info.frames[tile] and new_body != body:
                    raise ValueError(f'位置 ({x}, {y}) 有家具或其他带独立帧的物体。请换到空旷区域，避免破坏箱子、牌子等物品。')
                append(new_body, next_y - y, no_rle)
            y = next_y
    if pending is not None:
        _emit(buf, pending, pending_count, pending_no_rle)
    return buf


def material_version(result, version):
    if result.processing.get('materials_stale'):
        raise ValueError('像素画或材料设置已修改，请先重新生成三版本。')
    suffix = {'fine': '', 'wall': '_wall', 'map': '_map'}.get(version)
    if suffix is None:
        raise ValueError('请选择一种材料版本。')
    grid, palette = getattr(result, 'grid' + suffix), getattr(result, 'palette' + suffix)
    if grid is None or palette is None:
        raise ValueError('这份作品没有所选版本的材料，请先生成预览。')
    return grid, palette


def write_world(document, grid, palette, destination, *, x, y, scale=1, coating=True, overwrite=False,
                progress=None, cancelled=None, actuated=True):
    """校验后原子保存；直接保存仅允许覆盖输入世界，不生成备份。"""
    from .schematic import serialize_tile, FRAMES, ICE_BY_ROD
    destination = Path(destination).resolve()
    if destination.suffix.lower() != '.wld':
        raise ValueError('世界文件必须使用 .wld 后缀。')
    replacing = overwrite and destination == document.path
    if overwrite and not replacing:
        raise ValueError('直接保存只能写回当前选中的世界；其他位置请另存为新文件。')
    if not replacing and (destination == document.path or destination.exists()):
        raise ValueError('请选择一个新的文件名，原世界和已有文件不会被覆盖。')
    if not all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in (x, y, scale)) or scale < 1:
        raise ValueError('位置和放大倍数必须为整数，放大倍数至少为 1。')
    grid = np.asarray(grid)
    if grid.ndim != 2 or grid.dtype.kind not in 'iu' or not grid.size:
        raise ValueError('作品的材料网格不正确。')
    from .material_rules import validate_grid
    validate_grid(grid, palette)
    h, w = grid.shape
    info = document.info
    if x < 0 or y < 0 or x + w * scale > info.width or y + h * scale > info.height:
        raise ValueError(f'作品放置范围超出世界边界。世界为 {info.width}×{info.height} 格，作品为 {w * scale}×{h * scale} 格。')
    records = {}
    for index in np.unique(grid):
        if index == -1:
            continue  # 透明位置保持原来的完整格子，不清地形。
        if index < 0 or index >= len(palette.candidates):
            raise ValueError('作品含有无效的材料编号。')
        c = palette.candidates[int(index)]
        paint = c.paint['id']
        if not 0 <= paint <= 30:
            raise ValueError('作品含有不支持的喷漆编号。')
        if 'wall_id' in c.block:
            wall = c.block['wall_id']
            if not 0 < wall <= 65535:
                raise ValueError('作品含有无效的墙编号。')
            body = serialize_tile(False, 0, 0, 0, 0, wall, paint, False, coating)
            no_rle = False
        else:
            tile = c.block['tile_id']
            if tile == ICE_BY_ROD:
                raise ValueError('作品含临时冰块（ID 127），游戏无法持久保存，请先替换这种材料。')
            if not 0 <= tile < min(len(info.frames), len(FRAMES)) or info.frames[tile] != FRAMES[tile] or info.frames[tile]:
                raise ValueError(f'目标世界不支持物块 {tile}，或该素材需要独立家具帧；请先替换材料。')
            body = serialize_tile(True, tile, 0, 0, paint, 0, 0, coating, False, inactive=actuated)
            no_rle = tile in (423, 520)
        records[int(index)] = body, no_rle
    if not records:
        raise ValueError('当前画面全部透明，没有可导入的材料。')

    def notify(value, text):
        _check(cancelled)
        if progress:
            progress(value, text)

    notify(0, '准备放置像素画')
    tiles = bytearray()
    for column in range(info.width):
        _check(cancelled)
        if x <= column < x + w * scale:
            tiles.extend(_rewrite_column(document, column, grid, records, x, y, scale))
        else:
            a, b = document.columns[column:column + 2]
            tiles.extend(document.data[a:b])
        if column % 32 == 0:
            notify(round((column + 1) * 55 / info.width), '放置像素画')
    delta = len(tiles) - (info.pointers[2] - info.pointers[1])
    header = bytearray(document.data[:info.pointers[1]])
    for i, pointer in enumerate(info.pointers):
        struct.pack_into('<i', header, 26 + i * 4, pointer + (delta if i >= 2 else 0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.pixel-world-', suffix='.wld', dir=destination.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(header)
            file.write(tiles)
            file.write(document.data[info.pointers[2]:])
            file.flush()
            os.fsync(file.fileno())
        notify(60, '校验新世界')
        validated = load_world(temporary, overview=False, cancelled=cancelled,
                               progress=lambda p, text: notify(60 + round(p * .35), text))
        if validated.info.name != info.name or validated.info.world_id != info.world_id:
            raise ValueError('新世界校验失败，未保存。')
        notify(97, '检查原世界是否发生变化')
        if hashlib.sha256(document.path.read_bytes()).digest() != document.digest:
            raise ValueError('原世界在预览后发生了变化，请重新选择世界再导入。')
        notify(99, '保存新世界')
        if replacing:
            # 发布前再次核验；直接覆盖不保留额外的世界副本。
            _check(cancelled)
            if hashlib.sha256(document.path.read_bytes()).digest() != document.digest:
                raise ValueError('原世界在保存期间发生变化，已停止覆盖，请重新读取。')
            os.replace(temporary, destination)
        elif os.name == 'nt':
            os.rename(temporary, destination)  # Windows 原子发布，已存在则失败。
        else:
            os.link(temporary, destination)    # 同样不覆盖另一个进程创建的文件。
            temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if progress:
        progress(100, '新世界保存完成')
    return destination


def import_into_world(result, document, destination, *, version='fine', x=0, y=0, overwrite=False, progress=None, cancelled=None, coating=None):
    grid, palette = material_version(result, version)
    if coating is None:
        coating = False if version == 'map' else result.processing.get('coating', True)
    return write_world(document, grid, palette, destination, x=x, y=y, scale=result.scale,
                       coating=coating,
                       overwrite=overwrite, progress=progress, cancelled=cancelled)
