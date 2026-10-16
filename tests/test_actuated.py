"""虚化的真实文件标记、旧色快照兼容及易损素材的全入口限制。"""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from terraria_pixel.palette import Palette, PAINTS, mixed_palette, map_palette
from terraria_pixel.material_rules import (FALLING_TILES, FRAGILE_TILES, permitted,
                                           validate_grid, repair_grid)
from terraria_pixel.schematic import serialize_tile, write_tedsch
from terraria_pixel.world import load_world, write_world
from terraria_pixel.editor import EditCanvas
from terraria_pixel.material_library import catalog, data, ACTUATED_MODEL
from terraria_pixel.history import save_record, load_record
from terraria_pixel.pipeline import Result
from test_world import fixture, independent_tiles


class ActuatedTests(unittest.TestCase):
    def test_every_falling_and_fragile_material_is_blocked_even_with_support(self):
        for tile in FALLING_TILES | FRAGILE_TILES:
            with self.subTest(tile=tile):
                palette=Palette(blocks=[dict(tile_id=tile,rgb=(250,20,20)),
                                        dict(tile_id=1,rgb=(150,30,30))],paints=[PAINTS[0]])
                self.assertFalse(permitted(palette.blocks[0]))
                grid=np.array([[0],[1]],np.int32)
                with self.assertRaises(ValueError):
                    validate_grid(grid,palette)
                for map_colors in (False,True):
                    repaired=repair_grid(grid,palette,np.full((2,1,3),(250,20,20),np.uint8),map_colors=map_colors)
                    self.assertTrue(np.all(repaired == 1))
                canvas=EditCanvas(np.full((2,1,3),150,np.uint8),target='fine',
                                  indices=np.ones((2,1),np.int32),palette=palette)
                self.assertEqual(canvas.nearest_index((250,20,20)),1)
                with self.assertRaises(ValueError):
                    canvas.brush(0,0,index=0)
                with self.assertRaises(ValueError):
                    canvas.fill(0,0,index=0)
        self.assertTrue({51,62,69,127,162,352,481,482,483,655} <= FRAGILE_TILES)

    def test_actual_diagram_and_world_actuated_flags_with_rle_coating_and_alpha(self):
        palette=Palette(blocks=[dict(tile_id=1,rgb=(100,100,100)),
                                dict(wall_id=330,rgb=(90,90,90))],paints=[PAINTS[1]])
        grid=np.array([[0,1],[0,-1],[0,1]],np.int32)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            document=load_world(fixture(root/'source.wld'),overview=False)
            for coating in (False,True):
                diagram=root/f'{coating}.TEditSch'
                write_tedsch(grid,palette,diagram,name='虚化',scale=2,coating=coating)
                # 独立读取图纸名字、帧表和尺寸，再把逐格段放进测试世界头中。
                raw=diagram.read_bytes()
                import io, struct
                stream=io.BytesIO(raw)
                length=stream.read(1)[0]
                stream.read(length+4)
                frame_count=struct.unpack('<h',stream.read(2))[0]
                stream.read((frame_count+7)//8)
                width,height=struct.unpack('<II',stream.read(8))
                begin=stream.tell()
                # 使用独立流解码逐列记录，检查h3虚化位而不是依赖产品的解析器。
                for x in range(width):
                    y=0
                    while y<height:
                        h1=stream.read(1)[0]
                        h2=stream.read(1)[0] if h1&1 else 0
                        h3=stream.read(1)[0] if h2&1 else 0
                        h4=stream.read(1)[0] if h3&1 else 0
                        tile=int.from_bytes(stream.read(2 if h1&32 else 1),'little') if h1&2 else None
                        paint=stream.read(1)[0] if tile is not None and h3&8 else 0
                        wall=stream.read(1)[0] if h1&4 else 0
                        wall_paint=stream.read(1)[0] if h1&4 and h3&16 else 0
                        if h3&64:wall+=256*stream.read(1)[0]
                        count=int.from_bytes(stream.read(1 if h1>>6==1 else 2),'little') if h1>>6 else 0
                        self.assertEqual(h3&6,4 if tile is not None else 0)
                        self.assertEqual(h4,(8 if tile is not None else 16 if wall else 0) if coating else 0)
                        self.assertEqual(h2&254,0)
                        y+=count+1
                output=root/f'{coating}.wld'
                write_world(document,grid,palette,output,x=0,y=1,scale=2,coating=coating)
                cells=independent_tiles(load_world(output,overview=False))
                original=independent_tiles(document)
                for x in range(4):
                    for y in range(1,7):
                        index=grid[(y-1)//2,x//2]
                        if index<0:
                            self.assertEqual(cells[x][y],original[x][y])
                        else:
                            self.assertEqual(cells[x][y][5]&6,4 if index==0 else 0)
                            self.assertEqual(cells[x][y][6],(8 if index==0 else 16) if coating else 0)

    def test_actuated_texture_color_and_map_color_are_independent_and_snapshot_roundtrips(self):
        mixed=mixed_palette()
        tile=next(c for c in mixed.candidates if c.block.get('tile_id')==1 and c.paint['id']==26)
        self.assertEqual(tile.block['color_model'],ACTUATED_MODEL)
        self.assertLessEqual(max(tile.rgb),102)
        old=next(c for c in Palette().candidates if c.block.get('tile_id')==1 and c.paint['id']==26)
        self.assertGreater(max(old.rgb),max(tile.rgb))
        for candidate in mixed.candidates:
            if 'tile_id' in candidate.block and candidate.block.get('auto_eligible'):
                self.assertLessEqual(max(candidate.rgb),102)
        for entry in data()['materials']:
            if 'wall_id' in entry['material']:
                continue
            self.assertEqual(len(entry['actuated_colors']),31)
            self.assertEqual(len(entry['actuated_lab']),31)
            self.assertTrue(np.all(np.asarray(entry['actuated_variance'])>=0))
        # 同时保存原色库和新色库，历史文件的RGB/Lab快照不重新推算。
        with tempfile.TemporaryDirectory() as tmp:
            for palette in (Palette(),mixed,map_palette(walls=False)):
                result=Result(grid=np.zeros((1,1),np.int32),palette=palette,
                              processed_rgb=np.zeros((1,1,3),np.uint8),width=1,height=1,
                              original_size=(1,1),name='颜色快照',versions=('fine',))
                save_record(result,Path(tmp))
                restored=load_record(tmp).palette
                np.testing.assert_array_equal(restored.candidate_rgb_array(),palette.candidate_rgb_array())
                self.assertEqual(json.dumps(restored.blocks,sort_keys=True),json.dumps(palette.blocks,sort_keys=True))


if __name__=='__main__':unittest.main()
