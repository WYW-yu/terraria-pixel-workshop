"""生成可导入游戏的色卡：行=材质，列=喷漆，每个色块 9×9 格。"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from terraria_pixel.palette import BLOCKS, WALLS, PAINTS, Palette
from terraria_pixel.schematic import write_tedsch


def make_chart(output, catalog, ids, kind):
    bases = [b for ident in ids for b in catalog if b.get('tile_id', b.get('wall_id')) == ident]
    if len(bases) != len(ids):
        raise ValueError('色卡包含未校准材质 ID')
    palette = Palette(blocks=bases)
    grid = np.arange(len(palette.candidates), dtype=np.int32).reshape(len(bases), len(PAINTS))
    stem = '游戏颜色校验-' + kind
    write_tedsch(grid, palette, output / (stem + '.TEditSch'), scale=9, name=stem,
                walls_only=kind == '墙', coating=True)
    rgb = palette.candidate_rgb_array().reshape(len(bases), len(PAINTS), 3)
    Image.fromarray(rgb).resize((len(PAINTS)*9, len(bases)*9), Image.Resampling.NEAREST).save(output/(stem+'-平均色.png'))
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 14)
    canvas = Image.new('RGB', (210+len(PAINTS)*68, 65+len(bases)*60), '#152023')
    draw = ImageDraw.Draw(canvas)
    draw.text((12,12), '行：材质    列：喷漆 ID（无漆=0；每色块9×9格；已加夜明涂层）', font=font, fill='white')
    for x,p in enumerate(PAINTS): draw.text((228+x*68,43), str(p['id']), font=font, fill='white')
    for y,b in enumerate(bases):
        ident=b.get('tile_id',b.get('wall_id'))
        draw.text((12,83+y*60), f'{ident}  {b["name_zh"]}', font=font, fill='white')
        for x in range(len(PAINTS)):
            draw.rectangle((210+x*68,70+y*60,274+x*68,122+y*60), fill=tuple(map(int,rgb[y,x])))
    canvas.save(output/(stem+'-带编号.png'))
    mapping = dict(kind=kind, cell_size=9, coating=True, rows=[dict(id=b.get('tile_id',b.get('wall_id')), name=b['name_zh']) for b in bases],
                   columns=[dict(id=p['id'],name=p['name_zh']) for p in PAINTS])
    (output/(stem+'-编号.json')).write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
    print(stem, 'schematic size:',len(PAINTS)*9,'x',len(bases)*9)


if __name__ == '__main__':
    output=Path(sys.argv[1]); output.mkdir(parents=True,exist_ok=True)
    make_chart(output,BLOCKS,[1,38,155,147,30,40,202,267], '方块')
    make_chart(output,WALLS,[4,5,153,155,117,127,31,34], '墙')
    (output/'色卡使用说明.txt').write_text('导入对应 TEditSch 并粘贴到空旷位置，方块色卡和墙色卡分开放置，避免方块遮挡墙。\n'
        '每行一种材质，每列一个喷漆 ID，顺序见带编号 PNG 或编号 JSON。每个色块为9×9游戏格，均带夜明涂层。\n'
        '使用原版贴图；取各色块中心区域比较，避开拼接边缘。关闭影响画面颜色的滤镜，确保无液体覆盖或前景遮挡。\n'
        '平均色PNG是模型参考，不是游戏截图。随机帧、纹理和边缘会造成差异。此色卡用于实测，发行前尚未用游戏截图量测。\n',encoding='utf-8')
