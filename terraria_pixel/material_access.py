"""实际物品放置关系；物品编号、物块编号、墙编号分别存储。"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def access_data():
    return json.loads((Path(__file__).resolve().parents[1] / 'assets/material_access.json').read_text(encoding='utf-8'))


def wall_replacement(ident):
    """天然墙的可制作同名版本；返回的是墙 ID，不是物品 ID。"""
    return access_data()['wall_aliases'].get(str(ident))


def placement_items(block):
    kind = 'wall' if 'wall_id' in block else 'tile'
    return access_data()['placements'][kind].get(str(block.get(kind + '_id')), [])


def item_id_for(block):
    """旧记录的错误物品注释不能覆盖实际 createWall/createTile 关系。"""
    if 'wall_id' not in block:
        tool = access_data().get('tool_materials', {}).get(str(block.get('tile_id')))
        if tool:
            return tool['item_id']
    rows = placement_items(block)
    return next((r['item_id'] for r in rows if r['item_id'] == block.get('item_id')),
                rows[0]['item_id'] if rows else None)
