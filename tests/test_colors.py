"""独立游戏着色器结果回归，防止把小地图漆色当作材质乘数。"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terraria_pixel.color_model import paint_texels, mean_painted_color
from terraria_pixel.calibrated_colors import TILE_COLORS, WALL_COLORS
from terraria_pixel.palette import BLOCKS, WALLS, PAINTS, Palette, wall_palette


class ColorTests(unittest.TestCase):
    def test_against_independent_shader_bytecode_fixture(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' / 'tile_shader_white_vertex.json').read_text(encoding='utf-8'))
        for pid, expected in fixture['expected'].items():
            with self.subTest(paint=pid):
                np.testing.assert_allclose(paint_texels(fixture['rgb'], int(pid)), expected, rtol=0, atol=1e-5)
        for material in fixture['material_means']:
            table = WALL_COLORS if material['kind'] == 'wall' else TILE_COLORS
            for pid, expected in material['colors'].items():
                with self.subTest(material=material['id'], paint=pid):
                    # GPU 32 位常量与双精度公式在半整数舍入处可能差 1。
                    np.testing.assert_allclose(table[material['id']][int(pid)], expected, rtol=0, atol=1)

    def test_neutral_texel_keeps_secondary_channels(self):
        np.testing.assert_allclose(paint_texels((128,128,128), 13), (128,51.2,51.2))
        np.testing.assert_allclose(paint_texels((128,128,128), 20), (51.2,89.6,128))
        np.testing.assert_allclose(paint_texels((128,128,128), 25), (38.4,38.4,38.4))
        np.testing.assert_allclose(paint_texels((128,128,128), 27), (128,128,128))
        np.testing.assert_allclose(paint_texels((255,255,255), 28), (255,178.5,124.95))

    def test_white_paint_is_evaluated_before_averaging(self):
        checker = np.array([[0,0,0],[255,255,255]])
        self.assertEqual(mean_painted_color(checker, 26), (128,128,128))
        self.assertEqual(mean_painted_color(checker.mean(axis=0), 26), (191,191,191))

    def test_default_candidates_share_calibrated_baseline(self):
        from terraria_pixel.material_library import placed_tables
        tables = placed_tables()
        self.assertEqual((len(BLOCKS), len(WALLS)), (337, 366))
        for palette, kind, key in ((Palette(),'tile','tile_id'), (wall_palette(),'wall','wall_id')):
            for c in palette.candidates:
                self.assertEqual(c.rgb, tuple(tables[kind, c.block[key]][c.paint['id']]))
                self.assertEqual(c.block['rgb'], tuple(tables[kind, c.block[key]][0]))
        self.assertEqual([p['id'] for p in PAINTS], [0, *range(13,31)])
        for kind, old in (('tile', TILE_COLORS), ('wall', WALL_COLORS)):
            for ident, colors in old.items():
                if (kind, ident) in tables:
                    self.assertEqual(tables[kind, ident][:29], [list(c) for c in colors])
        for ident in (54, 160, 541):
            material = next(b for b in BLOCKS if b['tile_id'] == ident)
            self.assertTrue(material['estimate'])
            self.assertTrue(material['color_note'])

    def test_custom_rgb_does_not_inherit_installed_material_color(self):
        palette = Palette(blocks=[{'tile_id':1, 'rgb':(128,128,128)}], paints=[PAINTS[0], PAINTS[1]])
        self.assertEqual(palette.candidates[0].rgb, (128,128,128))
        self.assertEqual(palette.candidates[1].rgb, (128,51,51))


if __name__ == '__main__':
    unittest.main()
