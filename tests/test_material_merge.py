"""近色合并：色差上限、非传递替换、纹理保护、透明与保存一致性。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from terraria_pixel.formats import ConversionCancelled
from terraria_pixel.material_library import PLACED_MODEL
from terraria_pixel.material_merge import merge_similar_materials
from terraria_pixel.palette import Palette, PAINTS
from terraria_pixel.pipeline import prepare_pixel_preview, generate_material_versions, export_preview
from terraria_pixel.history import load_record
from terraria_pixel.quantize import rgb_to_lab
from test_core import read_schematic


def palette(colors, *, walls=False):
    return Palette(blocks=[dict(name=f'material{i}', name_zh=f'材料{i}',
        **({'wall_id': 4 + i} if walls else {'tile_id': i}), rgb=tuple(color))
        for i, color in enumerate(colors)], paints=[PAINTS[0]])


def texture_stats(pal, index, variance, offset=0, stable=True):
    block = pal.candidates[index].block
    mean = rgb_to_lab(block['rgb']) + [offset, 0, 0]
    block.update(color_model=PLACED_MODEL, auto_eligible=stable,
                 placed_lab=[mean.tolist()] * 31, placed_variance=[variance] * 31)


class MaterialMergeTests(unittest.TestCase):
    def test_frequency_representative_bound_and_no_chain(self):
        pal = palette([(100, 100, 100), (104, 104, 104), (108, 108, 108)])
        grid = np.array([[0] * 5 + [1] * 4 + [2] * 3 + [-1]])
        original = grid.copy()
        merged, report = merge_similar_materials(grid, pal, 2)
        np.testing.assert_array_equal(merged, [[0] * 9 + [2] * 3 + [-1]])
        np.testing.assert_array_equal(grid, original)
        self.assertEqual((report['before'], report['after'], report['changed_cells']), (3, 2, 4))
        self.assertLessEqual(report['max_distance'], 2)
        reverse, _ = merge_similar_materials(np.array([[0, 1, 1, 1]]), pal, 2)
        np.testing.assert_array_equal(reverse, [[1, 1, 1, 1]])

    def test_zero_disabled_transparency_and_invalid_arguments(self):
        pal = palette([(128, 128, 128)] * 2)
        source = np.array([[-1, 0, 1]])
        merged, report = merge_similar_materials(source, pal, 0)
        np.testing.assert_array_equal(merged, source)
        self.assertIsNot(merged, source)
        self.assertEqual(report['after'], 2)
        empty, report = merge_similar_materials(np.full((2, 3), -1), pal, 2)
        self.assertTrue(np.all(empty == -1))
        self.assertEqual(report['before'], 0)
        for invalid in (-1, 6, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                merge_similar_materials(source, pal, invalid)
        with self.assertRaises(ValueError):
            merge_similar_materials(np.array([[2]]), pal, 2)

    def test_texture_and_texel_mean_protect_same_average_rgb(self):
        for variance, offset in (([20, 20, 20], 0), ([0, 0, 0], 4)):
            pal = palette([(128, 128, 128)] * 2)
            texture_stats(pal, 0, [0, 0, 0])
            texture_stats(pal, 1, variance, offset)
            source = np.array([[0, 0, 0, 1]])
            merged, _ = merge_similar_materials(source, pal, 1.5)
            np.testing.assert_array_equal(merged, source)
            mapped, _ = merge_similar_materials(source, pal, 1.5, map_colors=True)
            np.testing.assert_array_equal(mapped, [[0, 0, 0, 0]])

    def test_target_cannot_increase_texture_variance_and_ties_prefer_flat(self):
        pal = palette([(128, 128, 128)] * 2)
        texture_stats(pal, 0, [.1, .1, .1])
        texture_stats(pal, 1, [0, 0, 0])
        source = np.array([[0, 0, 0, 1]])
        merged, _ = merge_similar_materials(source, pal, 2)
        np.testing.assert_array_equal(merged, source)
        tied, _ = merge_similar_materials(np.array([[0, 1]]), pal, 2)
        np.testing.assert_array_equal(tied, [[1, 1]])

    def test_unsafe_and_unstable_materials_never_become_representatives(self):
        pal = palette([(128, 128, 128)] * 3)
        pal.candidates[0].block['tile_id'] = 53
        texture_stats(pal, 1, [0, 0, 0], stable=False)
        source = np.array([[0, 0, 0, 1, 1, 2]])
        merged, _ = merge_similar_materials(source, pal, 2)
        np.testing.assert_array_equal(merged, source)

    def test_cancel_leaves_input_untouched(self):
        pal = palette([(128, 128, 128)] * 3)
        source = np.array([[0, 0, 1, 2, -1]])
        original = source.copy()
        state = {'cancel': False}
        def cancel():
            if state['cancel']:
                raise ConversionCancelled()
        def progress(value):
            state['cancel'] = True
        with self.assertRaises(ConversionCancelled):
            merge_similar_materials(source, pal, 2, cancel=cancel, progress=progress)
        np.testing.assert_array_equal(source, original)

    def test_pipeline_per_version_snapshot_schematic_and_reversible_regeneration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'image.png'
            Image.new('RGBA', (4, 2), (128, 128, 128, 255)).save(source)
            pixel = prepare_pixel_preview(source, width=4, material_merge=1.5)
            pixel.processed_rgb[0, 0, 3] = 0
            pixels = pixel.processed_rgb.copy()
            pal = palette([(128, 128, 128), (129, 129, 129)])
            wall = palette([(128, 128, 128), (129, 129, 129)], walls=True)
            map_pal = palette([(100, 0, 0), (0, 0, 255)])
            initial = np.array([[0, 0, 0, 1], [0, 0, 1, 1]], np.int32)
            def match(*args, **kwargs):
                return initial.copy()
            with patch('terraria_pixel.pipeline.match_materials', side_effect=match), \
                    patch('terraria_pixel.pipeline.wall_palette', return_value=wall), \
                    patch('terraria_pixel.pipeline.map_palette', return_value=map_pal), \
                    patch('terraria_pixel.pipeline.match_map', side_effect=match):
                result = generate_material_versions(pixel, palette=pal)
                restored = generate_material_versions(result, palette=pal, material_merge=0)
            self.assertIsNone(pixel.grid)
            np.testing.assert_array_equal(result.processed_rgb, pixels)
            for name in ('grid', 'grid_wall'):
                self.assertEqual(set(np.unique(getattr(result, name))), {-1, 0})
                self.assertEqual(set(np.unique(getattr(restored, name))), {-1, 0, 1})
            self.assertEqual(set(np.unique(result.grid_map)), {-1, 0, 1})
            self.assertEqual(result.processing['material_merge_report']['fine']['after'], 1)
            saved = export_preview(result, out_dir=root / 'out', make_schematic=True)
            loaded = load_record(saved.out_dir)
            self.assertEqual(loaded.processing['material_merge'], 1.5)
            for attr in ('grid', 'grid_wall', 'grid_map'):
                np.testing.assert_array_equal(getattr(loaded, attr), getattr(result, attr))
            tiles = read_schematic(saved.schematic)[3]
            self.assertIsNone(tiles[0][0][0])
            self.assertEqual(tiles[3][1][0], pal.candidates[0].block['tile_id'])


if __name__ == '__main__':
    unittest.main()
