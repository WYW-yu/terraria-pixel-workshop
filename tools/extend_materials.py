"""Append 1.4.5.8 material facts and calculate independent texture/map colors.

python tools/extend_materials.py <decoded-texture-directory>
Raw textures are calibration inputs only and are never packaged.
"""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.calibrate_colors import sample_frames
from terraria_pixel.color_model import paint_texels
from terraria_pixel.quantize import rgb_to_lab


def build(folder):
    path = ROOT / 'assets/library_materials.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    manifest = json.loads((ROOT / 'tools/material_additions_1458.json').read_text(encoding='utf-8'))
    positions = {(('wall',e['material']['wall_id']) if 'wall_id' in e['material'] else ('tile',e['material']['tile_id'])): i
                 for i, e in enumerate(data['materials'])}
    audit = []
    for fact in manifest['materials']:
        kind, ident = fact['kind'], fact['id']
        wall = kind == 'wall'
        stem = ('Wall_' if wall else 'Tiles_') + str(ident)
        raw = (folder / (stem+'.raw')).read_bytes()
        meta = json.loads((folder/(stem+'.json')).read_text())
        assert len(raw) == meta['w']*meta['h']*4
        frames = sample_frames(np.frombuffer(raw,np.uint8).reshape(meta['h'],meta['w'],4),wall)
        alpha = frames[...,3:4].astype(np.float64)/255
        notes = []
        if np.any(frames[...,3] != 255):
            notes.append('含透明或空洞，预览按白色背景合成')
        if meta['h'] > (180 if wall else 270) or (not wall and ident in (708,739,748)):
            notes.append('动画材质，预览使用首组密铺帧')
        if (wall and ident in (318,350)) or (not wall and ident in (717,718,719)):
            notes.append('隐形或特殊效果素材，预览仅作静态参考')
        tables = {key:[] for key in ('placed_colors','placed_lab','placed_variance','actuated_colors','actuated_lab','actuated_variance')}
        for paint in range(31):
            painted = np.rint(paint_texels(frames[...,:3],paint,wall=wall))
            for prefix, rendered in [('placed',painted)]+([] if wall else [('actuated',np.rint(painted*.4))]):
                composite = rendered*alpha + 255*(1-alpha)
                labs = rgb_to_lab(composite.reshape(-1,3))
                tables[prefix+'_colors'].append(np.rint(composite.reshape(-1,3).mean(0)).astype(int).tolist())
                tables[prefix+'_lab'].append(labs.mean(0).round(6).tolist())
                tables[prefix+'_variance'].append(labs.var(0).round(6).tolist())
        block = dict(name=fact['name'], name_zh=fact['name_zh'], **{kind+'_id':ident},
                     rgb=tables['placed_colors'][0], color_model='pixel-library-placed-v2',
                     estimate=bool(notes), color_note='；'.join(notes),auto_eligible=not notes,
                     placed_lab=tables.pop('placed_lab'),placed_variance=tables.pop('placed_variance'))
        entry = dict(material=block,map_rgb=fact['map_rgb'],map_source=manifest['map_source'],placed_colors=tables['placed_colors'])
        if not wall:
            entry.update({k:v for k,v in tables.items() if k.startswith('actuated')})
        if (kind, ident) in positions:
            data['materials'][positions[kind, ident]] = entry
        else:
            positions[kind, ident] = len(data['materials'])
            data['materials'].append(entry)
        audit.append(dict(kind=kind,id=ident,texture_sha256=meta['sha256'],raw_sha256=hashlib.sha256(raw).hexdigest(),
                          size=[meta['w'],meta['h']],map_rgb=fact['map_rgb'],note=block['color_note']))
    data['extension'] = 'terraria-1.4.5.8-64-materials-v1'
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (ROOT/'tools/additions_calibration.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Calculated',len(audit),'materials; total',len(data['materials']))

if __name__ == '__main__':
    build(Path(sys.argv[1]))
