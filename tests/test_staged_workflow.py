"""先像素后材料：无提前匹配、不重复调色、独立编辑及过期结果保护。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from terraria_pixel.pipeline import prepare_pixel_preview, generate_material_versions, prepare_preview, export_preview
from terraria_pixel.editor import EditCanvas
from terraria_pixel.formats import ConversionCancelled
from terraria_pixel.world import material_version


class StagedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.png'
        rgb = np.random.default_rng(516).integers(0, 256, (4, 6, 4), np.uint8)
        rgb[..., 3] = 255
        rgb[0, 0, 3] = 0
        Image.fromarray(rgb).save(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def test_pixel_stage_never_constructs_or_matches_materials(self):
        with patch('terraria_pixel.pipeline.mixed_palette', side_effect=AssertionError('early palette')), \
                patch('terraria_pixel.pipeline.match_materials', side_effect=AssertionError('early match')), \
                patch('terraria_pixel.pipeline.match_map', side_effect=AssertionError('early map')):
            pixel = prepare_pixel_preview(self.source, width=6)
        self.assertIsNone(pixel.grid)
        self.assertIsNone(pixel.palette)
        self.assertEqual(pixel.versions, ())
        self.assertEqual(pixel.processed_rgb.shape, (4, 6, 4))
        self.assertEqual({p.name for p in self.root.iterdir()}, {'source.png'})

    def test_confirm_uses_edited_pixels_without_original_file_or_second_processing(self):
        pixel = prepare_pixel_preview(self.source, width=6, gamma=1.8, contrast=1.3, color_limit=8)
        canvas = EditCanvas.from_result(pixel, 'pixel')
        canvas.set_cell(2, 1, rgb=(17, 63, 91))
        canvas.apply_to(pixel)
        expected = pixel.processed_rgb.copy()
        self.source.unlink()
        with patch('terraria_pixel.pipeline.pixelate', side_effect=AssertionError('second pixelate')), \
                patch('terraria_pixel.pipeline.load_image_pixels', side_effect=AssertionError('reread original')):
            generated = generate_material_versions(pixel)
        np.testing.assert_array_equal(generated.processed_rgb, expected)
        self.assertEqual(tuple(generated.processed_rgb[1, 2, :3]), (17, 63, 91))
        self.assertEqual(generated.versions, ('fine', 'wall', 'map'))
        self.assertIsNone(pixel.grid)
        for grid in (generated.grid, generated.grid_wall, generated.grid_map):
            self.assertEqual(grid[0, 0], -1)

    def test_split_matches_existing_one_step_for_all_dithers(self):
        for dither in ('none', 'bayer', 'floyd'):
            with self.subTest(dither=dither):
                pixel = prepare_pixel_preview(self.source, width=6, dither=dither)
                staged = generate_material_versions(pixel)
                combined = prepare_preview(self.source, width=6, dither=dither)
                for attr in ('processed_rgb', 'grid', 'grid_wall', 'grid_map'):
                    np.testing.assert_array_equal(getattr(staged, attr), getattr(combined, attr))

    def test_each_material_editor_changes_only_its_own_grid(self):
        result = prepare_preview(self.source, width=6)
        for key, attr in (('fine', 'grid'), ('wall', 'grid_wall'), ('map', 'grid_map')):
            before = {name: getattr(result, name).copy() for name in ('grid', 'grid_wall', 'grid_map', 'processed_rgb')}
            canvas = EditCanvas.from_result(result, key)
            canvas.set_cell(2, 1, rgb=(0, 0, 0, 0))
            canvas.apply_to(result)
            self.assertEqual(getattr(result, attr)[1, 2], -1)
            for name, array in before.items():
                if name != attr:
                    np.testing.assert_array_equal(getattr(result, name), array)
            self.assertFalse(result.processing.get('materials_stale'))

    def test_pixel_edit_blocks_stale_exports_until_reconfirmed(self):
        result = prepare_preview(self.source, width=6)
        canvas = EditCanvas.from_result(result, 'pixel')
        canvas.set_cell(2, 1, rgb=(1, 2, 3))
        canvas.apply_to(result)
        self.assertTrue(result.processing['materials_stale'])
        with self.assertRaisesRegex(ValueError, '重新生成'):
            export_preview(result, out_dir=self.root / 'out')
        with self.assertRaisesRegex(ValueError, '重新生成'):
            material_version(result, 'fine')
        refreshed = generate_material_versions(result)
        self.assertFalse(refreshed.processing['materials_stale'])
        export_preview(refreshed, out_dir=self.root / 'out')

    def test_cancel_does_not_mutate_pixel_or_previous_material_edits(self):
        result = prepare_preview(self.source, width=6)
        before = {attr: getattr(result, attr).copy() for attr in ('processed_rgb', 'grid', 'grid_wall', 'grid_map')}
        state = {'cancel': False}
        def progress(value, text):
            if value >= 45:
                state['cancel'] = True
        with self.assertRaises(ConversionCancelled):
            generate_material_versions(result, progress=progress, cancelled=lambda: state['cancel'])
        for attr, array in before.items():
            np.testing.assert_array_equal(getattr(result, attr), array)


if __name__ == '__main__':
    unittest.main()
