"""导入 既有色库 材料 ID 与地图色表，并独立从游戏纹素生成建筑用色。

python tools/import_material_library.py <既有色库目录> <解码纹理目录>
不复制对方 EXE/DLL，不执行对方代码；完整查询表作为数据供地图版使用。
"""
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.calibrate_colors import sample_frames, SPECIAL_TILES
from terraria_pixel.color_model import paint_texels
from terraria_pixel.palette_data import BLOCKS
from terraria_pixel.wall_data import WALLS
from terraria_pixel.quantize import rgb_to_lab
from terraria_pixel.tedsch_frames import TILE_FRAME_IMPORTANT


def build(source_library, textures):
    raw = (source_library / 'files/all.tr').read_bytes()
    count, = struct.unpack_from('<H', raw)
    if len(raw) != 2 + count * 7 + 2**25:
        raise ValueError('既有色库 色表长度不正确')
    names = json.loads((source_library / 'ItemID.json').read_text(encoding='utf-8-sig'))
    known = {(True, b['tile_id']): b for b in BLOCKS}
    known.update({(False, b['wall_id']): b for b in WALLS})
    materials, seen, audit = [], set(), []
    for i in range(count):
        ident, pid, tile, r, g, b = struct.unpack_from('<HBBBBB', raw, 2 + i * 7)
        key = bool(tile), ident
        if key in seen:
            continue
        seen.add(key)
        stem = ('Tiles_' if tile else 'Wall_') + str(ident)
        meta = json.loads((textures / (stem + '.json')).read_text())
        pixels = np.frombuffer((textures / (stem + '.raw')).read_bytes(), np.uint8).reshape(meta['h'], meta['w'], 4)
        frames = sample_frames(pixels, not tile)
        notes = []
        if tile and ident in SPECIAL_TILES:
            notes.append('变色、隐形或附加特效，预览仅作静态参考')
        if meta['h'] > (270 if tile else 180):
            notes.append('动画材质，预览使用首组密铺帧')
        if np.any(frames[..., 3] != 255):
            notes.append('含透明或空洞，预览按白色背景合成')
        if tile and ident == 127:
            notes.append('临时冰块无法持久保存到游戏图纸，请换材料后导出图纸')
        alpha = frames[..., 3:4].astype(np.float64) / 255
        colors, lab_means, lab_variances = [], [], []
        for paint in range(31):
            painted = np.rint(paint_texels(frames[..., :3], paint, wall=not tile))
            # 对不透明材料保持旧版的逐纹素量化后平均；透明材料明确采用白底参考。
            composite = painted * alpha + 255 * (1 - alpha)
            colors.append(np.rint(composite.reshape(-1, 3).mean(axis=0)).astype(int).tolist())
            labs = rgb_to_lab(composite.reshape(-1, 3))
            lab_means.append(labs.mean(axis=0).round(6).tolist())
            lab_variances.append(labs.var(axis=0).round(6).tolist())
        old = known.get(key, {})
        entry = dict(name=old.get('name', ('Tile' if tile else 'Wall') + str(ident)),
                     name_zh=names['Tiles' if tile else 'Walls'].get(str(ident), f'材料 {ident}'),
                     **{('tile_id' if tile else 'wall_id'): ident},
                     rgb=colors[0], color_model='pixel-library-placed-v2',
                     estimate=bool(notes), color_note='；'.join(notes))
        if 'item_id' in old:
            entry['item_id'] = old['item_id']
        # 自动匹配不使用依赖背景、时间、特效或家具帧的材料；手选仍保留完整素材库。
        entry['auto_eligible'] = not notes and not (tile and (ident >= len(TILE_FRAME_IMPORTANT) or TILE_FRAME_IMPORTANT[ident])) and not (not tile and ident == 318)
        entry['placed_lab'] = lab_means
        entry['placed_variance'] = lab_variances
        materials.append(dict(material=entry, placed_colors=colors, map_rgb=[r, g, b]))
        audit.append(dict(kind='tile' if tile else 'wall', id=ident, texture_sha256=meta['sha256'],
                          size=[meta['w'], meta['h']], note=entry['color_note']))
    data = dict(model='pixel-library-placed-v2', game_version='1.4.5.8',
                matching='expected-texel-lab-v2', library_sha256=hashlib.sha256(raw).hexdigest(), materials=materials)
    (ROOT / 'assets/library_materials.json').write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    shutil.copyfile(source_library / 'files/all.tr', ROOT / 'assets/library_all.tr')
    for kind in ('tile', 'wall'):
        shutil.copyfile(source_library / f'files/{kind}.tr', ROOT / f'assets/library_{kind}.tr')
    from tools.compress_map_tables import build as compress_maps
    compress_maps(ROOT / 'assets')
    (ROOT / 'tools/library_calibration.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Imported', len(materials), 'materials;', sum(bool(m['material']['color_note']) for m in materials), 'with static-preview notes')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
