"""逐纹素选材、墙负漆和原世界直接保存的行为回归。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from terraria_pixel.color_model import paint_texels
from terraria_pixel.palette import Palette, wall_palette, PAINTS
from terraria_pixel.pipeline import match_materials
from terraria_pixel.quantize import rgb_to_lab, CHROMA_WEIGHT
from terraria_pixel.material_library import PLACED_MODEL
from terraria_pixel.world import load_world, write_world
from test_world import fixture, independent_tiles


class PlacedMatchingTests(unittest.TestCase):
    def test_new_paints_against_shader_vm(self):
        data = json.loads((Path(__file__).parent / 'fixtures' / 'negative_shader.json').read_text())
        for wall in (False, True):
            for pid in (29, 30):
                np.testing.assert_allclose(paint_texels(data['rgb'], pid, wall=wall),
                    data['wall' if wall else 'tile'][str(pid)], atol=1e-5)
        negative = [p for p in PAINTS if p['id'] == 30]
        self.assertEqual(Palette(blocks=[dict(wall_id=1, rgb=(64,64,64))], paints=negative).candidates[0].rgb, (63,63,63))

    def test_mean_texture_error_rejects_misleading_average(self):
        # 平均色完全相同：棋盘纹理与平整灰色，后者实际每个纹素更接近目标。
        texels = np.array([[20, 20, 20], [220, 220, 220]])
        textured = dict(tile_id=1, rgb=(120, 120, 120), color_model=PLACED_MODEL,
                        auto_eligible=True, placed_lab=[rgb_to_lab(texels).mean(axis=0).tolist()] * 31,
                        placed_variance=[rgb_to_lab(texels).var(axis=0).tolist()] * 31)
        flat = dict(tile_id=2, rgb=(125, 125, 125))
        from terraria_pixel.palette import Candidate
        palette = Palette(blocks=[], paints=[])
        palette._candidates = [Candidate(textured, PAINTS[0], (120, 120, 120)),
                               Candidate(flat, PAINTS[0], (125, 125, 125))]
        rgb = np.full((4, 5, 3), 120, np.uint8)
        for mode in ('none', 'bayer', 'floyd'):
            self.assertTrue(np.all(match_materials(rgb, palette, dither=mode) == 1))

    def test_placed_auto_excludes_background_dependent_materials_all_dithers(self):
        for palette in (Palette(), wall_palette()):
            labs, costs, allowed = palette.matching_data()
            self.assertTrue(allowed.any())
            self.assertTrue((~allowed).any())
            self.assertTrue(np.all(costs >= 0))
            for c, ok in zip(palette.candidates, allowed):
                if ok:
                    self.assertFalse(c.block.get('estimate'))
            rgb = np.random.default_rng(410).integers(0, 256, (7, 8, 3), np.uint8)
            for mode in ('none', 'bayer', 'floyd'):
                grid = match_materials(rgb, palette, dither=mode)
                self.assertTrue(allowed[grid].all())
            # 独立逐纹素二次损失，与匹配结果比较；不依赖颜色表的平均 RGB。
            target = rgb_to_lab(rgb)[..., None, :]
            dist = ((target - labs) ** 2 * [1, CHROMA_WEIGHT, CHROMA_WEIGHT]).sum(axis=-1) + costs
            dist[..., ~allowed] = np.inf
            np.testing.assert_array_equal(match_materials(rgb, palette), dist.argmin(axis=-1))


class DirectWorldTests(unittest.TestCase):
    def test_direct_save_no_backup_and_second_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = fixture(Path(tmp) / 'world.wld')
            old = source.read_bytes()
            existing_backup = Path(str(source) + '.bak')
            existing_backup.write_bytes(b'existing user backup')
            palette = Palette(blocks=[dict(wall_id=4, rgb=(120, 120, 120))], paints=[PAINTS[0]])
            grid = np.zeros((2, 2), np.int32)
            document = load_world(source, overview=False)
            write_world(document, grid, palette, source, x=0, y=0, overwrite=True)
            self.assertEqual(existing_backup.read_bytes(), b'existing user backup')
            after = source.read_bytes()
            self.assertNotEqual(after, old)
            self.assertEqual(independent_tiles(load_world(source, overview=False))[0][0][1], 4)
            write_world(load_world(source, overview=False), grid, palette, source, x=3, y=0, overwrite=True)
            self.assertNotEqual(source.read_bytes(), after)
            self.assertEqual(list(Path(tmp).glob('*.bak')), [existing_backup])
            self.assertEqual(existing_backup.read_bytes(), b'existing user backup')
            with self.assertRaisesRegex(ValueError, '发生了变化'):
                write_world(document, grid, palette, source, x=0, y=0, overwrite=True)

    def test_failed_atomic_replace_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = fixture(Path(tmp) / 'world.wld')
            original = source.read_bytes()
            palette = Palette(blocks=[dict(wall_id=4, rgb=(120, 120, 120))], paints=[PAINTS[0]])
            with patch('terraria_pixel.world.os.replace', side_effect=PermissionError('world busy')):
                with self.assertRaises(PermissionError):
                    write_world(load_world(source, overview=False), np.zeros((1, 1), np.int32),
                                palette, source, x=0, y=0, overwrite=True)
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(list(Path(tmp).glob('*.bak')))
            self.assertFalse(list(Path(tmp).glob('.pixel-world-*')))

    def test_source_changed_before_replace_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = fixture(Path(tmp) / 'world.wld')
            original = source.read_bytes()
            palette = Palette(blocks=[dict(wall_id=4, rgb=(120,120,120))], paints=[PAINTS[0]])
            def changed(value, text):
                if value == 99:
                    source.write_bytes(original + b'other program saved')
            with self.assertRaisesRegex(ValueError, '保存期间发生变化'):
                write_world(load_world(source, overview=False), np.zeros((1,1),np.int32), palette,
                            source, x=0, y=0, overwrite=True, progress=changed)
            self.assertEqual(source.read_bytes(), original + b'other program saved')
            self.assertFalse(list(Path(tmp).glob('.pixel-world-*')))


if __name__ == '__main__':
    unittest.main()
