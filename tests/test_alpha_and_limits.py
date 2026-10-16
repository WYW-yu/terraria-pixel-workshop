"""透明编辑/草稿/图纸一致性，以及仅图纸限制尺寸的回归。"""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from terraria_pixel.editor import EditCanvas
from terraria_pixel.drafts import Draft, save_draft, load_draft, import_image
from terraria_pixel.pipeline import prepare_preview, export_preview
from terraria_pixel.history import load_record
from terraria_pixel.pixels import png_image, material_pixels
from terraria_pixel.draft_paths import remember_draft, open_folder, recent_drafts
from test_core import read_schematic


class AlphaAndLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_transparent_brush_fill_and_undo_keep_prior_strokes(self):
        canvas = EditCanvas.blank(5, 4)
        canvas.set_cell(2, 1, rgb=(255, 0, 0))
        canvas.set_cell(0, 0, rgb=(0, 0, 0, 0))
        self.assertEqual(canvas.rgb.shape[2], 4)
        self.assertEqual(canvas.color_at(0, 0), (0, 0, 0, 0))
        canvas.undo(); self.assertEqual(canvas.color_at(0, 0), (255, 255, 255, 255))
        canvas.undo(); self.assertEqual(canvas.color_at(2, 1), (255, 255, 255, 255))
        canvas.redo(); canvas.redo()
        canvas.fill(4, 3, rgb=(0, 0, 0, 0))
        self.assertEqual(np.count_nonzero(canvas.rgb[..., 3]), 1)
        canvas.fill(0, 0, rgb=(0, 255, 0))
        self.assertEqual(canvas.color_at(0, 0), (0, 255, 0, 255))

    def test_draft_and_import_preserve_alpha_and_state(self):
        pixels = np.zeros((3, 4, 4), np.uint8)
        pixels[1, 2] = (10, 20, 30, 128)
        path = self.root/'draft.tpdraft'
        save_draft(path, Draft(EditCanvas(pixels), (0, 0, 0, 0), 'fill', ((0,0,0,0),)))
        loaded = load_draft(path)
        np.testing.assert_array_equal(loaded.canvas.rgb, pixels)
        self.assertEqual(loaded.color, (0,0,0,0))
        self.assertEqual(loaded.history, ((0,0,0,0),))
        image = self.root/'image.png'; Image.fromarray(pixels).save(image)
        np.testing.assert_array_equal(import_image(image).canvas.rgb, pixels)

    def test_transparent_source_empty_tiles_history_and_material_draft(self):
        pixels = np.zeros((3, 4, 4), np.uint8)
        pixels[1, 2] = (180, 80, 40, 255)
        source = self.root/'input.png'; Image.fromarray(pixels).save(source)
        preview = prepare_preview(source, width=4, sampling='nearest')
        np.testing.assert_array_equal(preview.processed_rgb, pixels)
        self.assertEqual(np.count_nonzero(preview.grid >= 0), 1)
        self.assertEqual(material_pixels(preview.grid, preview.palette)[0, 0, 3], 0)
        saved = export_preview(preview, out_dir=self.root/'out', make_schematic=True)
        restored = load_record(saved.out_dir)
        np.testing.assert_array_equal(restored.processed_rgb, pixels)
        np.testing.assert_array_equal(restored.grid_wall, preview.grid_wall)
        columns = read_schematic(saved.schematic)[3]
        self.assertEqual(columns[0][0], (None, None, 0, 0, 0))
        candidate = preview.palette.candidates[int(preview.grid[1, 2])]
        self.assertEqual(columns[2][1][1 if 'wall_id' in candidate.block else 0],
                         candidate.block.get('wall_id', candidate.block.get('tile_id')))
        material = EditCanvas.from_result(restored, 'fine')
        material.set_cell(2, 1, rgb=(0,0,0,0))
        path = self.root/'material.tpdraft'; save_draft(path, Draft(material))
        loaded = load_draft(path).canvas
        np.testing.assert_array_equal(loaded.rgb, material.rgb)
        np.testing.assert_array_equal(loaded.indices, material.indices)

    def test_png_grid_is_optional_and_preserves_interior_transparency(self):
        values = np.zeros((2, 3, 4), np.uint8); values[0, 1] = (10,20,30,255)
        raw = png_image(values)
        np.testing.assert_array_equal(np.asarray(raw), values)
        grid = png_image(values, grid=True, cell_size=12)
        self.assertEqual(grid.size, (36,24))
        self.assertEqual(grid.getpixel((6,6))[3], 0)
        self.assertEqual(grid.getpixel((18,6)), (10,20,30,255))
        self.assertGreater(grid.getpixel((0,0))[3], 0)

    def test_large_pixel_image_allowed_but_schematic_rejected_without_partial_files(self):
        path = self.root/'large.png'; Image.new('RGB', (5001,2), 'red').save(path)
        preview = prepare_preview(path, width=5001, sampling='nearest')
        self.assertEqual(preview.width, 5001)
        self.assertEqual(import_image(path).canvas.width, 5001)
        saved = export_preview(preview, out_dir=self.root/'data', make_schematic=False)
        self.assertTrue(saved.out_dir.is_dir())
        with self.assertRaises(ValueError):
            export_preview(preview, out_dir=self.root/'schematic', make_schematic=True)
        self.assertFalse((self.root/'schematic').exists())

    def test_draft_open_uses_last_custom_save_location(self):
        path = self.root/'custom'/'art.tpdraft'
        save_draft(path, Draft(EditCanvas.blank(2,2)))
        remember_draft(self.root, path)
        self.assertEqual(open_folder(self.root), path.parent)
        self.assertIn(path, recent_drafts(self.root))
