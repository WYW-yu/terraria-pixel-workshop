"""从解码后的当前游戏纹理生成颜色库；不将游戏纹理打包进程序。

运行：python tools/calibrate_colors.py <raw-dir>
取样：方块三个全邻接 16×16 帧；墙 Framing.centerWallFrameLookup 的
九格周期 × 三个随机帧，取绘制矩形中心 16×16。边界拼接仍有纹理误差。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terraria_pixel.palette_data import BLOCKS
from terraria_pixel.wall_data import WALLS
from terraria_pixel.color_model import mean_painted_color

# 不稳定材质：实时变色、隐形或附加特效，不能以一张基础贴图代表。
SPECIAL_TILES = {160, 541, 659, 667, 692, 370, 687, 688, 689, 690, 691}
WALL_GROUPS = (((36,36),(72,36),(108,36)),
               ((216,36),(252,36),(288,36)),
               ((216,72),(252,72),(288,72)),
               ((360,0),(360,36),(360,72)),
               ((396,0),(396,36),(396,72)))
CENTER_WALL = (2,0,0,0,1,4,0,3,0)


def sample_frames(a, wall=False):
    coords = [xy for group in CENTER_WALL for xy in WALL_GROUPS[group]] if wall else [(18,18),(36,18),(54,18)]
    inset = 8 if wall else 0
    frames = [a[y+inset:y+inset+16,x+inset:x+inset+16] for x,y in coords]
    if any(f.shape != (16,16,4) for f in frames):
        raise ValueError('缺少标准放置帧')
    return np.stack(frames)


def build(folder):
    colors = {'tile': {}, 'wall': {}}
    evidence = {'game_version': '1.4.5.8', 'model': 'placed-texel-white-vertex-v1',
                'condition': '原版贴图；夜明涂层/白色满亮度；标准密铺帧', 'materials': [], 'excluded': []}
    for kind, bases in (('tile',BLOCKS), ('wall',WALLS)):
        for b in bases:
            ident = b[kind+'_id']
            name = ('Tiles_' if kind=='tile' else 'Wall_')+str(ident)
            meta = json.loads((folder/(name+'.json')).read_text())
            a = np.frombuffer((folder/(name+'.raw')).read_bytes(),np.uint8).reshape(meta['h'],meta['w'],4)
            reason = None
            if kind=='tile' and ident in SPECIAL_TILES:
                reason = '实时变色/隐形/附加特效未校准'
            elif meta['h'] > (180 if kind=='wall' else 270):
                reason = '动画或特殊多帧绘制未校准'
            try:
                frames = sample_frames(a,kind=='wall')
                if np.any(frames[...,3] != 255):
                    reason = '透明/空洞颜色依赖背景'
            except ValueError as e:
                reason = str(e)
            entry = dict(kind=kind,id=ident,name=b['name_zh'],sha256=meta['sha256'],size=[meta['w'],meta['h']])
            if reason:
                evidence['excluded'].append(dict(entry,reason=reason))
                continue
            rgb = frames[...,:3]
            table = [mean_painted_color(rgb,pid) for pid in range(29)]
            colors[kind][ident] = table
            evidence['materials'].append(dict(entry,base_rgb=table[0],frames=len(frames)))
    output = ROOT/'terraria_pixel'/'calibrated_colors.py'
    lines = ['"""自动生成：Terraria 1.4.5.8 原版放置帧，逐纹素喷漆，白色绘制顶点。"""',
             'MODEL_VERSION = "placed-texel-white-vertex-v1"', 'GAME_VERSION = "1.4.5.8"']
    for kind in colors:
        lines.append(kind.upper()+'_COLORS = {')
        for ident, table in colors[kind].items():
            lines.append(f'    {ident}: {tuple(table)!r},')
        lines.append('}')
    output.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    audit = ROOT/'tools'/'color_calibration.json'
    audit.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:len(v) for k,v in colors.items()},'excluded:',len(evidence['excluded']))


if __name__=='__main__':
    build(Path(sys.argv[1]))
