"""地图版：原序候选、原始 RGB 查询表和同分选后者规则。"""
from functools import lru_cache
import struct

import numpy as np

from .map_storage import MAP_COUNTS, candidate_records, table_bytes

PAINT_RGB = ((255, 0, 0), (255, 127, 0), (255, 255, 0), (127, 255, 0),
             (0, 255, 0), (0, 255, 127), (0, 255, 255), (0, 127, 255),
             (0, 0, 255), (127, 0, 255), (255, 0, 255), (255, 0, 127),
             (75, 75, 75), (255, 255, 255), (175, 175, 175), (255, 178, 125), (25, 25, 25))


def map_painted_color(rgb, paint, wall=False):
    base = np.asarray(rgb, dtype=np.float32)
    if paint == 0:
        return tuple(map(int, base))
    if paint == 30:
        color = (255 - base) * np.float32(.5 if wall else 1)
    elif 13 <= paint <= 29:
        factor = base[2] / np.float32(255) * np.float32(.3) if paint == 29 else base.max() / np.float32(255)
        color = np.array(PAINT_RGB[paint - 13], np.float32) * factor
    else:
        raise ValueError('地图版仅支持无漆及 13–30 号喷漆')
    return tuple(map(int, color.astype(np.uint8)))


@lru_cache(maxsize=3)
def lookup(walls=None):
    kind = 'all' if walls is None else 'wall' if walls else 'tile'
    count = MAP_COUNTS[kind]
    # 首次使用验证候选次序，防止查询表与素材库错位。
    from .palette import map_palette
    records = candidate_records(kind)
    palette = map_palette(walls=walls)
    if len(palette.candidates) < count:
        raise ValueError('地图材料数量与查询表不一致')
    for i, c in enumerate(palette.candidates[:count]):
        ident, paint, tile, r, g, b = struct.unpack_from('<HBBBBB', records, i * 7)
        if (ident, paint, tile, r, g, b) != (c.block.get('wall_id', c.block.get('tile_id')),
                                            c.paint['id'], int('tile_id' in c.block), *c.rgb):
            raise ValueError('地图材料顺序与查询表不一致')
    return np.frombuffer(table_bytes(kind), dtype='<u2')


@lru_cache(maxsize=3)
def matching_colors(walls):
    # The installed map palette is immutable; editing/history use separate palettes.
    from .palette import map_palette
    colors = map_palette(walls=walls).candidate_rgb_array().astype(np.int32)
    colors.setflags(write=False)
    return colors


def match_map(rgb, progress=None, cancel=None, *, walls=None):
    pixels = np.asarray(rgb, dtype=np.uint8)
    flat = pixels.reshape(-1, 3)
    result = np.empty(len(flat), np.int32)
    table = lookup(walls)
    legacy_count = 12141 if walls is None else 6270 if walls else 5871
    colors = matching_colors(walls)
    extra = colors[legacy_count:]
    for start in range(0, len(flat), 65536):
        if cancel:
            cancel()
        part = flat[start:start + 65536]
        # Keep the exact legacy lookup, then compare appended colors. Duplicates
        # still select the last candidate, including ties with legacy materials.
        unique, inverse = np.unique(part.astype(np.int32), axis=0, return_inverse=True)
        old = np.asarray(table[(unique[:,0] << 16) | (unique[:,1] << 8) | unique[:,2]],dtype=np.int32)
        for offset in range(0,len(unique),1024):
            if cancel:
                cancel()
            query = unique[offset:offset+1024]
            current = old[offset:offset+len(query)]
            if len(extra):
                distances = np.square(query[:, 0:1] - extra[None, :, 0])
                distances += np.square(query[:, 1:2] - extra[None, :, 1])
                distances += np.square(query[:, 2:3] - extra[None, :, 2])
                choice = len(extra)-1-np.argmin(distances[:,::-1],axis=1)
                distance = distances[np.arange(len(query)),choice]
                prior = np.sum((query-colors[current])**2,axis=1)
                old[offset:offset+len(query)] = np.where(distance<=prior,legacy_count+choice,current)
        result[start:start + len(part)] = old[inverse]
        if progress:
            progress((start + len(part)) / len(flat))
    return result.reshape(pixels.shape[:2])


def nearest_rgb(rgb, candidates):
    delta = np.asarray(candidates, dtype=np.int32) - np.asarray(rgb[:3], dtype=np.int32)
    distances = (delta * delta).sum(axis=1)
    return len(distances) - 1 - int(np.argmin(distances[::-1]))
