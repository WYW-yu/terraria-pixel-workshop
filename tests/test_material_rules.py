"""传播源排除、重力支撑、混合选材以及两种写入格式的行为验证。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from terraria_pixel.material_rules import (SPREADING_TILES, FALLING_TILES, permitted,
                                           repair_grid, validate_grid)
from terraria_pixel.palette import Palette, PAINTS, mixed_palette, map_palette, wall_palette
from terraria_pixel.pipeline import prepare_preview, export_preview
from terraria_pixel.editor import EditCanvas
from terraria_pixel.schematic import write_tedsch
from terraria_pixel.world import load_world, write_world
from test_core import read_schematic
from test_world import fixture, independent_tiles


def sample_palette():
    return Palette(blocks=[dict(tile_id=1, rgb=(30,30,30), name_zh='石块'),
                           dict(tile_id=53, rgb=(240,20,20), name_zh='沙块'),
                           dict(wall_id=4, rgb=(20,20,240), name_zh='墙'),
                           dict(tile_id=25, rgb=(20,240,20), name_zh='黑檀石块')], paints=[PAINTS[0]])


class MaterialRulesTests(unittest.TestCase):
    def test_game_flags_include_unusual_spreaders_and_falling_coin_piles(self):
        self.assertEqual(len(SPREADING_TILES), 30)
        self.assertTrue({492,636,661,662,32,352,115} <= SPREADING_TILES)
        self.assertEqual(FALLING_TILES, {53,234,112,116,224,123,330,331,332,333,495})
        for tile in SPREADING_TILES:
            self.assertFalse(permitted(dict(tile_id=tile)))
        # 黑檀石砖、猩红石砖、珍珠石砖不会传播；不按名称误删。
        for tile in (38,152,118):
            self.assertTrue(permitted(dict(tile_id=tile)))
        self.assertTrue(permitted(dict(wall_id=25)))

    def test_mixed_default_uses_both_placed_libraries(self):
        mixed = mixed_palette()
        self.assertEqual(len(mixed.blocks), 703)
        labs, costs, allowed = mixed.matching_data()
        selected = [c for c, ok in zip(mixed.candidates, allowed) if ok]
        self.assertTrue(any('tile_id' in c.block for c in selected))
        self.assertTrue(any('wall_id' in c.block for c in selected))
        self.assertTrue(all(permitted(c.block) for c in selected))
        self.assertTrue(all('wall_id' in b for b in wall_palette().blocks))
        self.assertTrue(all('wall_id' in b for b in map_palette(walls=True).blocks))
        self.assertTrue(all('tile_id' in b for b in map_palette(walls=False).blocks))

    def test_repair_removes_all_gravity_and_infection_preserves_holes(self):
        palette = sample_palette()
        original = np.array([[1,1,1,1], [0,2,-1,3], [0,2,-1,1]],np.int32)
        rgb = palette.candidate_rgb_array()[np.maximum(original,0)]
        for map_colors in (False,True):
            result = repair_grid(original,palette,rgb,map_colors=map_colors)
            validate_grid(result,palette)
            self.assertFalse(np.any(result == 1))
            self.assertNotEqual(result[0,1],1)
            self.assertNotEqual(result[0,2],1)
            self.assertNotEqual(result[2,3],1)
            self.assertFalse(np.any(result == 3))
            np.testing.assert_array_equal(result[:,2], [result[0,2],-1,-1])
            self.assertEqual(original[2,3],1)

    def test_edit_support_replacement_and_selection_fill_are_one_undo(self):
        palette = sample_palette()
        canvas = EditCanvas(np.full((3,2,3),30,np.uint8), target='fine',
                            indices=np.zeros((3,2),np.int32),palette=palette)
        with self.assertRaisesRegex(ValueError,'重力'):
            canvas.set_cell(0,1,index=1)
        before = canvas.indices.copy()
        canvas.set_cell(0,2,index=2)
        self.assertNotEqual(canvas.indices[1,0],1)
        validate_grid(canvas.indices,palette)
        canvas.undo()
        np.testing.assert_array_equal(canvas.indices,before)
        canvas.redo()
        validate_grid(canvas.indices,palette)
        with self.assertRaisesRegex(ValueError,'重力'):
            canvas.fill_rectangle((0,0,1,2),index=1)
        self.assertFalse(np.any(canvas.indices[-1] == 1))
        validate_grid(canvas.indices,palette)
        with self.assertRaisesRegex(ValueError,'传播'):
            canvas.set_cell(0,0,index=3)

    def test_pipeline_all_dithers_and_map_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'image.png'
            colors=np.random.default_rng(411).integers(0,256,(6,8,4),np.uint8)
            colors[...,3]=255
            colors[3,2]=0
            Image.fromarray(colors).save(path)
            for dither in ('none','bayer','floyd'):
                result=prepare_preview(path,width=8,sampling='nearest',dither=dither)
                for grid,palette in ((result.grid,result.palette),(result.grid_map,result.palette_map),
                                     (result.grid_wall,result.palette_wall)):
                    validate_grid(grid,palette)
                    self.assertEqual(grid[3,2],-1)
                self.assertEqual(result.processing['placed_material_scope'],'mixed-tile-wall')

    def test_mixed_tile_wall_write_and_unsafe_old_exports_rejected(self):
        palette=sample_palette()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            grid=np.array([[0,2],[0,-1]],np.int32)
            schematic=root/'mixed.TEditSch'
            write_tedsch(grid,palette,schematic,name='mixed')
            columns=read_schematic(schematic)[3]
            self.assertEqual(columns[0][0],(1,None,0,0,8))
            self.assertEqual(columns[1][0],(None,4,0,0,16))
            source=fixture(root/'source.wld')
            document=load_world(source,overview=False)
            write_world(document,grid,palette,root/'mixed.wld',x=1,y=1)
            cells=independent_tiles(load_world(root/'mixed.wld',overview=False))
            self.assertEqual(cells[1][1][:4],(1,0,0,0))
            self.assertEqual(cells[1][1][5] & 6,4)  # 虚化且没有额外致动器
            self.assertEqual(cells[1][1][6],8)
            self.assertEqual(cells[2][1][:4],(None,4,0,0))
            self.assertEqual(cells[2][1][6],16)
            self.assertEqual(cells[2][1][5] & 6,0)
            for index,reason in ((3,'传播'),(1,'重力')):
                bad=np.full((1,1),index,np.int32)
                with self.assertRaisesRegex(ValueError,reason):
                    write_tedsch(bad,palette,root/'bad.TEditSch',name='bad')
                with self.assertRaisesRegex(ValueError,reason):
                    write_world(document,bad,palette,root/'bad.wld',x=0,y=0)
                self.assertFalse((root/'bad.wld').exists())
                self.assertFalse((root/'bad.TEditSch').exists())
            self.assertEqual(source.read_bytes(),document.data)


if __name__ == '__main__':
    unittest.main()
