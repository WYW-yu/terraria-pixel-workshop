"""降采样质量、真实调色板抖动及两种导出的端到端验证。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terraria_pixel.image_io import pixelate, is_pixel_grid
from terraria_pixel.pipeline import run_conversion, ConversionCancelled
from terraria_pixel.quantize import match_to_palette, rgb_to_lab
from test_core import read_schematic


class AlgorithmTests(unittest.TestCase):
    def test_auto_preserves_expanded_pixel_art_exactly(self):
        art = np.random.default_rng(7).integers(0, 256, (9, 13, 3), dtype=np.uint8)
        expanded = art.repeat(6, axis=0).repeat(6, axis=1)
        self.assertTrue(is_pixel_grid(expanded))
        np.testing.assert_array_equal(pixelate(expanded, 13), art)
        np.testing.assert_array_equal(pixelate(art, 13), art)

    def test_area_suppresses_sampling_aliases(self):
        checker = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
        rgb = np.repeat(checker[..., None], 3, axis=2)
        self.assertFalse(is_pixel_grid(rgb))
        old = pixelate(rgb, 32, sampling="nearest")
        new = pixelate(rgb, 32)
        self.assertGreater(np.abs(old.astype(float) - 127.5).mean(), 120)
        self.assertLess(np.abs(new.astype(float) - 127.5).mean(), 1)

    def test_color_controls_and_limits(self):
        rgb = np.random.default_rng(4).integers(0, 256, (40, 60, 3), dtype=np.uint8)
        limited = pixelate(rgb, 30, color_limit=8)
        self.assertLessEqual(len(np.unique(limited.reshape(-1, 3), axis=0)), 8)
        grey = pixelate(rgb, 60, saturation=0)
        np.testing.assert_array_equal(grey[..., 0], grey[..., 1])
        np.testing.assert_array_equal(grey[..., 1], grey[..., 2])
        flat = np.full((5, 5, 3), 64, dtype=np.uint8)
        self.assertGreater(pixelate(flat, 5, gamma=2).mean(), flat.mean())
        for kwargs in ({"color_limit": 1}, {"sampling": "bad"}, {"gamma": 0}, {"detail": float("nan")}):
            with self.assertRaises(ValueError):
                pixelate(flat, 5, **kwargs)

    def test_dither_represents_average_perceptual_tone(self):
        palette = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
        rgb = np.full((64, 64, 3), 128, dtype=np.uint8)
        target = rgb_to_lab(rgb)[..., 0].mean()
        nearest = match_to_palette(rgb, palette)
        baseline = abs(rgb_to_lab(palette[nearest])[..., 0].mean() - target)
        for mode in ("bayer", "floyd"):
            grid = match_to_palette(rgb, palette, dither=mode, strength=1)
            self.assertEqual(set(np.unique(grid)), {0, 1})
            error = abs(rgb_to_lab(palette[grid])[..., 0].mean() - target)
            self.assertLess(error, 6)
            self.assertLess(error, baseline / 5)
            np.testing.assert_array_equal(grid, match_to_palette(rgb, palette, dither=mode, strength=1))
            np.testing.assert_array_equal(nearest, match_to_palette(rgb, palette, dither=mode, strength=0))

    def test_duplicate_colors_single_color_and_exact_palette(self):
        palette = np.array([[0, 0, 0], [0, 0, 0], [255, 255, 255]], dtype=np.uint8)
        rgb = np.full((16, 16, 3), 128, dtype=np.uint8)
        self.assertEqual(len(np.unique(match_to_palette(rgb, palette, dither="bayer", strength=1))), 2)
        for mode in ("bayer", "floyd"):
            self.assertTrue(np.all(match_to_palette(rgb, palette[:1], dither=mode) == 0))
            exact = palette[[0, 2, 0, 2]][None, ...]
            np.testing.assert_array_equal(palette[match_to_palette(exact, palette, dither=mode)], exact)

    def test_dither_cancellation(self):
        rgb = np.random.default_rng(3).integers(0, 256, (20, 30, 3), dtype=np.uint8)
        for mode in ("bayer", "floyd"):
            calls = []
            def cancel():
                calls.append(1)
                if len(calls) > 1:
                    raise ConversionCancelled()
            with self.assertRaises(ConversionCancelled):
                match_to_palette(rgb, [[0, 0, 0], [255, 255, 255]], dither=mode, chunk=1, cancel=cancel)

    def test_dither_exports_and_color_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = np.random.default_rng(12).integers(0, 256, (12, 16, 3), dtype=np.uint8)
            path = root / "source.png"
            Image.fromarray(source).save(path)
            for mode in ("bayer", "floyd"):
                progress = []
                result = run_conversion(path, width=16, color_limit=8,
                    dither=mode, make_schematic=True, out_dir=root / "out", scale=2,
                    progress=lambda value, _: progress.append(value))
                self.assertEqual(progress, sorted(progress))
                self.assertEqual(progress[-1], 100)
                settings = json.loads((result.out_dir / "作品记录.json").read_text(encoding="utf-8"))["processing"]
                self.assertEqual(settings["dither"], mode)
                self.assertLessEqual(len(np.unique(result.processed_rgb.reshape(-1, 3), axis=0)), 8)
                for grid, palette, schematic, wall in (
                    (result.grid, result.palette, result.schematic, False),
                    (result.grid_wall, result.palette_wall, result.schematic_wall, True)):
                    expected = palette.candidate_rgb_array()[grid]
                    from terraria_pixel.history import load_record
                    restored = load_record(result.out_dir)
                    restored_grid = restored.grid_wall if wall else restored.grid
                    np.testing.assert_array_equal(palette.candidate_rgb_array()[restored_grid], expected)
                    _, width, height, columns = read_schematic(schematic)
                    self.assertEqual((width, height), (32, 24))
                    for x in range(width):
                        for y in range(height):
                            candidate = palette.candidates[int(grid[y // 2, x // 2])]
                            record = columns[x][y]
                            is_wall = 'wall_id' in candidate.block
                            self.assertEqual(record[1 if is_wall else 0], candidate.block["wall_id" if is_wall else "tile_id"])
                            self.assertEqual(record[3 if is_wall else 2], candidate.paint["id"])
                self.assertFalse(list(result.out_dir.glob("*.png")))
                self.assertFalse(list(result.out_dir.glob("*.html")))
                self.assertFalse(list(result.out_dir.glob("*.txt")))


if __name__ == "__main__":
    unittest.main()
