"""从原纹素补充虚化物块色表，保留原放置色和地图色供旧作品使用。

python tools/build_actuated_colors.py <解码纹理目录>
游戏 GetFinalLight 在夜明/白色光之后调用 Tile.actColor，RGB乘0.4，Alpha不变。
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


def build(textures):
    path = ROOT / 'assets/library_materials.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    audit = []
    for entry in data['materials']:
        block = entry['material']
        if 'wall_id' in block:
            continue
        stem = 'Tiles_' + str(block['tile_id'])
        raw = (textures / (stem + '.raw')).read_bytes()
        meta = json.loads((textures / (stem + '.json')).read_text())
        if len(raw) != meta['w'] * meta['h'] * 4:
            raise ValueError('解码纹理尺寸不完整：' + stem)
        pixels = np.frombuffer(raw, np.uint8).reshape(meta['h'], meta['w'], 4)
        frames = sample_frames(pixels)
        alpha = frames[..., 3:4].astype(np.float64) / 255
        colors, means, variances = [], [], []
        for paint in range(31):
            cached = np.rint(paint_texels(frames[..., :3], paint))
            # 白色顶点255经过actColor得到102，Alpha仍为255；以8位目标量化。
            rendered = np.rint(cached * (102 / 255))
            composite = rendered * alpha + 255 * (1 - alpha)
            colors.append(np.rint(composite.reshape(-1, 3).mean(axis=0)).astype(int).tolist())
            labs = rgb_to_lab(composite.reshape(-1, 3))
            means.append(labs.mean(axis=0).round(6).tolist())
            variances.append(labs.var(axis=0).round(6).tolist())
        entry.update(actuated_colors=colors, actuated_lab=means, actuated_variance=variances)
        audit.append(dict(tile_id=block['tile_id'], texture_sha256=meta['sha256'],
                          raw_sha256=hashlib.sha256(raw).hexdigest()))
    data['actuated_model'] = 'pixel-library-actuated-v1'
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    (ROOT / 'tools/actuated_calibration.json').write_text(json.dumps(dict(
        game_version='1.4.5.8', vertex_rgb=[102,102,102], vertex_alpha=255,
        quantization='8bit-nearest', materials=audit), indent=2), encoding='utf-8')
    print('Actuated texture tables:', len(audit))


if __name__ == '__main__':
    build(Path(sys.argv[1]))
