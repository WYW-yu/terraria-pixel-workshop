"""材料库；建筑贴图色和地图 RGB 永远使用不同的数据字段。"""
import json
import struct
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
PLACED_MODEL = 'pixel-library-placed-v2'
ACTUATED_MODEL = 'pixel-library-actuated-v1'
MAP_MODEL = 'pixel-map-rgb-v1'


def normalize_color_metadata(value):
    """更新旧作品的模型标签，保留颜色快照、候选次序和其他字段。"""
    if isinstance(value, dict):
        return {key: normalize_color_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_color_metadata(item) for item in value]
    if isinstance(value, str):
        for suffix, model in (('-library-placed-v2', PLACED_MODEL),
                              ('-library-actuated-v1', ACTUATED_MODEL),
                              ('-map-rgb-v1', MAP_MODEL)):
            if value.endswith(suffix):
                return model
    return value


@lru_cache(maxsize=1)
def data():
    return json.loads((ASSETS / 'library_materials.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def placed_tables():
    return {(('wall', e['material']['wall_id']) if 'wall_id' in e['material'] else ('tile', e['material']['tile_id'])):
            e['placed_colors'] for e in data()['materials']}


@lru_cache(maxsize=1)
def actuated_tables():
    return {e['material']['tile_id']: e['actuated_colors'] for e in data()['materials']
            if 'tile_id' in e['material']}


@lru_cache(maxsize=2)
def map_bases(walls):
    """单独物块表有少量基础色不同于混合表，必须跟随所选查询表。"""
    from .map_storage import candidate_records
    records = candidate_records('wall' if walls else 'tile')
    return {ident: (r, g, b) for ident, paint, tile, r, g, b in struct.iter_unpack('<HBBBBB', records) if paint == 0}


def catalog(walls=False, map_colors=False, *, actuated=False):
    result = []
    for e in data()['materials']:
        b = e['material']
        if walls is not None and ('wall_id' in b) != walls:
            continue
        b = dict(b)
        b['translucent_wall'] = 'wall_id' in b and '透明' in b.get('color_note', '')
        if map_colors:
            for field in ('placed_lab', 'placed_variance', 'auto_eligible'):
                b.pop(field, None)
            rgb = e['map_rgb'] if walls is None else map_bases(walls).get(b.get('wall_id', b.get('tile_id')), e['map_rgb'])
            b.update(rgb=tuple(rgb), color_model=MAP_MODEL, estimate=False,
                     color_note='地图显示颜色；与游戏主画面的贴图颜色不同')
        else:
            b['rgb'] = tuple(b['rgb'])
            if actuated and 'tile_id' in b:
                b.update(rgb=tuple(e['actuated_colors'][0]), color_model=ACTUATED_MODEL,
                         placed_lab=e['actuated_lab'], placed_variance=e['actuated_variance'],
                         actuated=True)
        result.append(b)
    return result
