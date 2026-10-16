"""Import audited Item.createTile/createWall relations; item IDs are not world IDs.

Input is a static export of the local 1.4.5.8 Item.SetDefaults methods.
Only metadata is updated: calibrated texture colors and map records keep their IDs.
"""
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def update(placement_path, localization_path):
    audit = json.loads(placement_path.read_text(encoding='utf-8-sig'))
    if audit['errors']:
        raise ValueError('Item placement audit contains errors')
    localized = json.loads(localization_path.read_text(encoding='utf-8-sig'))['ItemName']
    library_path = ROOT / 'assets/library_materials.json'
    library = json.loads(library_path.read_text(encoding='utf-8'))
    items = {kind: {} for kind in ('tile', 'wall')}
    for row in audit['placements']:
        for kind in items:
            ident = row[kind]
            if ident < (1 if kind == 'wall' else 0):
                continue
            items[kind].setdefault(ident, []).append(dict(
                item_id=row['item_id'], item_name=row['item_name'],
                item_name_zh=localized.get(row['item_name'], row['item_name']),
                place_style=row['style']))
    walls = {e['material']['wall_id']: e for e in library['materials'] if 'wall_id' in e['material']}
    aliases = {}
    for ident, entry in walls.items():
        if ident in items['wall'] or ident in (272, 273, 350):
            continue
        choices = [i for i, e in walls.items() if i in items['wall']
                   and e['material']['name_zh'] == entry['material']['name_zh']]
        if ident == 349:
            choices = [1]
        if len(choices) != 1:
            raise ValueError(f'Ambiguous natural wall replacement: {ident}: {choices}')
        aliases[ident] = choices[0]
    if len(aliases) != 71:
        raise ValueError('Unexpected wall alias count')
    for entry in library['materials']:
        block = entry['material']
        kind = 'wall' if 'wall_id' in block else 'tile'
        ident = block[kind + '_id']
        choices = items[kind].get(ident, [])
        chosen = next((r for r in choices if r['item_id'] == block.get('item_id')), choices[0] if choices else None)
        block['item_id'] = chosen['item_id'] if chosen else None
        if chosen:
            block['item_name_zh'] = chosen['item_name_zh']
            if kind == 'wall':
                # Distinguish obtainable special unsafe-wall items from crafted walls.
                block['name_zh'] = chosen['item_name_zh']
        else:
            block.pop('item_name_zh', None)
        if kind == 'tile' and ident == 194:
            # Bone Block item 766 has no normal acquisition route. The Bone Wand
            # (932, createTile=194, tileWand=154) consumes ordinary Bones instead.
            block.update(item_id=154, item_name_zh=localized['Bone'], build_tool_item_id=932)
        if kind == 'wall' and ident in aliases:
            block['replacement_wall_id'] = aliases[ident]
    manifest = dict(game_version='1.4.5.8',
        source='Item.SetDefaults1–5: createTile/createWall and DefaultToPlaceableTile/Wall',
        input_sha256=hashlib.sha256(placement_path.read_bytes()).hexdigest(),
        wall_aliases=aliases, unavailable_walls=[272, 273, 350], unavailable_tiles=[668],
        tool_materials={'194': dict(item_id=154, item_name='Bone', item_name_zh=localized['Bone'],
                                    tool_item_id=932, tool_name_zh=localized['BoneWand'])},
        placements={kind: {i: rows for i, rows in entries.items()
                           if i in {e['material'].get(kind+'_id') for e in library['materials']}}
                    for kind, entries in items.items()})
    (ROOT / 'assets/material_access.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    library['access_model'] = 'item-placement-1.4.5.8-v1'
    library_path.write_text(json.dumps(library, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    # Keep the older calibration input metadata consistent, without changing its
    # world IDs or color samples.
    for kind, filename in (('wall', 'wall_data.py'), ('tile', 'palette_data.py')):
        current = {e['material'][kind+'_id']: e['material']['item_id'] for e in library['materials'] if kind+'_id' in e['material']}
        path = ROOT / 'terraria_pixel' / filename
        pattern = re.compile(r"('"+kind+r"_id': (\d+), 'item_id': )([^,]+)")
        text = pattern.sub(lambda m: m[1]+repr(current[int(m[2])]), path.read_text(encoding='utf-8'))
        path.write_text(text, encoding='utf-8')
    print('Updated metadata:', len(aliases), 'wall aliases;', len(items['wall']), 'actual placeable wall IDs')


if __name__ == '__main__':
    update(Path(sys.argv[1]), Path(sys.argv[2]))
