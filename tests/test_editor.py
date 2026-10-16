"""像素画编辑数据层的测试：色库规则、改格、填充、撤销重做、写回结果。"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from terraria_pixel.editor import (TARGET_FINE, TARGET_PIXEL, TARGET_WALL, EditCanvas,
                                   MATERIAL_TARGETS)
from terraria_pixel.pipeline import prepare_preview


def make_result(tmp: Path):
    """造一张小图并跑一遍转换，拿到带两个材料版本的 Result。"""
    img = np.zeros((10, 10, 3), np.uint8)
    img[..., 0] = np.linspace(0, 255, 10)[None, :]
    img[..., 1] = np.linspace(0, 255, 10)[:, None]
    img[..., 2] = 120
    path = tmp / "in.png"
    Image.fromarray(img).save(path)
    return prepare_preview(path, width=10, progress=lambda *_: None)


class TestPixelCanvas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.result = make_result(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_pixel_target_accepts_any_color(self):
        canvas = EditCanvas.from_result(self.result, TARGET_PIXEL)
        self.assertFalse(canvas.is_material)
        self.assertTrue(canvas.set_cell(0, 0, rgb=(1, 2, 3)))
        self.assertEqual(canvas.color_at(0, 0), (1, 2, 3))
        self.assertTrue(canvas.dirty)
        canvas.apply_to(self.result)
        self.assertEqual(tuple(int(v) for v in self.result.processed_rgb[0, 0]), (1, 2, 3))

    def test_material_target_snaps_to_palette(self):
        canvas = EditCanvas.from_result(self.result, TARGET_FINE)
        self.assertTrue(canvas.is_material)
        before = canvas.index_at(3, 3)
        canvas.set_cell(3, 3, rgb=(250, 5, 5))
        after = canvas.index_at(3, 3)
        self.assertNotEqual(before, after)
        candidates = canvas.candidates
        self.assertEqual(canvas.color_at(3, 3), tuple(int(v) for v in candidates[after]))
        self.assertTrue(canvas.label_of(after))

    def test_wall_target_uses_wall_library(self):
        canvas = EditCanvas.from_result(self.result, TARGET_WALL)
        self.assertTrue(canvas.labels)
        for index in range(len(canvas.labels)):
            self.assertIn("wall_id", canvas.palette.candidates[index].block.keys())
        canvas.set_cell(1, 1, index=0)
        self.assertEqual(canvas.index_at(1, 1), 0)

    def test_fill_and_undo_redo(self):
        canvas = EditCanvas.from_result(self.result, TARGET_PIXEL)
        original = tuple(int(v) for v in canvas._orig_rgb[0, 0])
        for x in (0, 1, 2):
            self.assertTrue(canvas.set_cell(x, 0, rgb=(0, 0, 0)))
        count = canvas.fill(0, 0, rgb=(9, 9, 9))
        self.assertGreaterEqual(count, 3)
        self.assertEqual(canvas.color_at(2, 0), (9, 9, 9))

        canvas.undo()                                   # 撤销填充
        self.assertEqual(canvas.color_at(2, 0), (0, 0, 0))
        for _ in range(3):                              # 撤销三次改格
            canvas.undo()
        self.assertEqual(canvas.color_at(0, 0), original)
        self.assertFalse(canvas.dirty)

        for _ in range(4):                              # 重做回填充后的状态
            canvas.redo()
        self.assertEqual(canvas.color_at(2, 0), (9, 9, 9))
        self.assertTrue(canvas.dirty)

    def test_reset_restores_original(self):
        canvas = EditCanvas.from_result(self.result, TARGET_FINE)
        canvas.fill(0, 0, rgb=(1, 1, 1))
        self.assertTrue(canvas.dirty)
        canvas.reset()
        self.assertFalse(canvas.dirty)

    def test_bounds_and_errors(self):
        canvas = EditCanvas.from_result(self.result, TARGET_FINE)
        with self.assertRaises(IndexError):
            canvas.set_cell(99, 99, rgb=(1, 1, 1))
        self.assertEqual(canvas.nearest_index(canvas.color_at(0, 0)), canvas.index_at(0, 0))
        pixel = EditCanvas.from_result(self.result, TARGET_PIXEL)
        with self.assertRaises(ValueError):
            pixel.nearest_index((1, 1, 1))

    def test_apply_only_touches_its_own_version(self):
        pixel_before = np.array(self.result.processed_rgb, copy=True)
        grid_before = np.array(self.result.grid, copy=True)
        fine = EditCanvas.from_result(self.result, TARGET_FINE)
        fine.set_cell(0, 0, index=(fine.index_at(0, 0) + 1) % len(fine.labels))
        fine.apply_to(self.result)
        np.testing.assert_array_equal(self.result.processed_rgb, pixel_before)   # 材料版不动像素画
        self.assertFalse(np.array_equal(self.result.grid, grid_before))
        grid_after = np.array(self.result.grid, copy=True)
        pixel = EditCanvas.from_result(self.result, TARGET_PIXEL)
        pixel.set_cell(0, 0, rgb=(7, 7, 7))
        pixel.apply_to(self.result)
        self.assertEqual(tuple(int(v) for v in self.result.processed_rgb[0, 0]), (7, 7, 7))
        np.testing.assert_array_equal(self.result.grid, grid_after)              # 像素画不动材料版

    def test_blank_canvas_can_be_converted(self):
        canvas = EditCanvas.blank(16, 24, (10, 20, 30))
        self.assertFalse(canvas.is_material)
        self.assertEqual((canvas.width, canvas.height), (16, 24))
        self.assertEqual(canvas.color_at(0, 0), (10, 20, 30))
        self.assertFalse(canvas.dirty)
        self.assertTrue(canvas.set_cell(3, 4, rgb=(255, 0, 0)))
        self.assertTrue(canvas.dirty)
        path = Path(self.tmp.name) / "hand-drawn.png"
        Image.fromarray(canvas.to_array()).save(path)
        result = prepare_preview(path, width=16, progress=lambda *_: None)
        self.assertEqual(result.grid.shape, (24, 16))
        self.assertEqual(len(canvas.to_array().shape), 3)

    def test_blank_canvas_rejects_bad_size(self):
        for size in ((0, 10), (10, 0), (-1, 10)):
            with self.assertRaises(ValueError):
                EditCanvas.blank(*size)

    def test_rejects_missing_data(self):
        result = make_result(Path(self.tmp.name))
        result.grid = None
        with self.assertRaises(ValueError):
            EditCanvas.from_result(result, TARGET_FINE)

    def test_apply_checkpoint_retains_undo_and_reset(self):
        canvas = EditCanvas.blank(8, 8)
        canvas.set_cell(0, 0, rgb=(1, 2, 3))
        canvas.mark_applied()
        self.assertFalse(canvas.dirty)
        canvas.undo()
        self.assertTrue(canvas.dirty)
        canvas.redo()
        self.assertFalse(canvas.dirty)
        canvas.reset()
        self.assertTrue(canvas.dirty)

    def test_one_stroke_is_one_undo_even_if_cell_revisited(self):
        canvas = EditCanvas.blank(8, 8)
        canvas.begin_stroke()
        for x in range(8):
            canvas.set_cell(x, 0, rgb=(10, 20, 30))
        canvas.set_cell(0, 0, rgb=(90, 80, 70))
        canvas.end_stroke()
        canvas.undo()
        self.assertFalse(canvas.can_undo)
        self.assertFalse(canvas.dirty)
        canvas.redo()
        self.assertEqual(canvas.color_at(0, 0), (90, 80, 70))
        self.assertEqual(canvas.color_at(7, 0), (10, 20, 30))

    def test_block_material_edit_roundtrips(self):
        from terraria_pixel.pipeline import export_preview
        from terraria_pixel.history import load_record
        canvas = EditCanvas.from_result(self.result, TARGET_FINE)
        canvas.set_cell(0, 0, index=canvas.nearest_index((255, 0, 0)))
        canvas.apply_to(self.result)
        saved = export_preview(self.result, out_dir=Path(self.tmp.name) / "out", make_schematic=True)
        loaded = load_record(saved.out_dir)
        np.testing.assert_array_equal(loaded.grid, canvas.indices)

    def test_empty_rejected_and_large_pixel_canvas_allowed(self):
        with self.assertRaises(ValueError):
            EditCanvas(np.empty((0, 1, 3), dtype=np.uint8))
        canvas = EditCanvas.blank(5000, 2)
        self.assertEqual(canvas.width, 5000)

    def test_canvas_owns_input_memory(self):
        pixels = np.zeros((4, 4, 3), dtype=np.uint8)
        canvas = EditCanvas(pixels)
        canvas.set_cell(0, 0, rgb=(1, 2, 3))
        np.testing.assert_array_equal(pixels, np.zeros_like(pixels))

    def test_fill_cannot_reconnect_through_outside_selection(self):
        canvas = EditCanvas.blank(5, 5)
        # 选区内两侧被黑线隔开，选区外的白色却可绕过黑线相连。
        canvas.rgb[1:4, 2] = (0, 0, 0)
        original = canvas.rgb.copy()
        changed = canvas.fill(1, 2, rgb=(20, 80, 150), bounds=(1, 1, 3, 3))
        self.assertEqual(changed, 3)
        expected = original.copy()
        expected[1:4, 1] = (20, 80, 150)
        np.testing.assert_array_equal(canvas.rgb, expected)
        canvas.undo()
        np.testing.assert_array_equal(canvas.rgb, original)


if __name__ == "__main__":
    unittest.main()
