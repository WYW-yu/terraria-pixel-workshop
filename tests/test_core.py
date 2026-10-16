"""核心回归检查：颜色一致性、清单数量、取消清理及独立图纸解析。"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terraria_pixel.image_io import load_image_rgb, image_size
from terraria_pixel.palette import Palette, PAINTS
from terraria_pixel.pipeline import ConversionCancelled, run_conversion
from terraria_pixel.quantize import CHROMA_WEIGHT, match_to_palette, rgb_to_lab
from terraria_pixel.materials import _stats
from terraria_pixel.schematic import write_tedsch
from terraria_pixel.tedsch_frames import TILE_FRAME_IMPORTANT


def read_schematic(path):
    """独立读取器：返回名称、尺寸及 (tile, wall, tilePaint, wallPaint, coating) 记录。"""
    data = Path(path).read_bytes()
    cursor = 0

    def take(fmt):
        nonlocal cursor
        values = struct.unpack_from(fmt, data, cursor)
        cursor += struct.calcsize(fmt)
        return values

    def string():
        nonlocal cursor
        size = shift = 0
        while True:
            byte, = take("<B")
            size |= (byte & 127) << shift
            if byte < 128:
                break
            shift += 7
        value = data[cursor:cursor + size].decode("utf-8")
        cursor += size
        return value

    name = string()
    marker, = take("<I")
    frames, = take("<h")
    cursor += (frames + 7) // 8
    width, height = take("<II")
    columns = []
    for _ in range(width):
        column = []
        while len(column) < height:
            h1, = take("<B")
            h2 = h3 = h4 = 0
            if h1 & 1:
                h2, = take("<B")
                if h2 & 1:
                    h3, = take("<B")
                    if h3 & 1:
                        h4, = take("<B")
            tile, wall, tile_paint, wall_paint = None, None, 0, 0
            if h1 & 2:
                tile, = take("<B")
                if h1 & 32:
                    high, = take("<B")
                    tile |= high << 8
                if TILE_FRAME_IMPORTANT[tile]:
                    take("<hh")
                if h3 & 8:
                    tile_paint, = take("<B")
            if h1 & 4:
                wall, = take("<B")
                if h3 & 16:
                    wall_paint, = take("<B")
            if h3 & 64:
                high, = take("<B")
                wall |= high << 8
            rle = (h1 >> 6) & 3
            repeat = take("<B")[0] if rle == 1 else take("<h")[0] if rle == 2 else 0
            if repeat < 0:
                raise AssertionError("RLE overflow")
            column.extend([(tile, wall, tile_paint, wall_paint, h4)] * (repeat + 1))
        if len(column) != height:
            raise AssertionError("Column height mismatch")
        columns.append(column)
    assert take("<hhI") == (0, 0, 0)
    assert string() == name
    assert take("<III") == (marker - 10000, width, height)
    assert cursor == len(data)
    return name, width, height, columns


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.image = self.root / "sample.png"
        Image.fromarray(np.array([[[255, 0, 0], [255, 255, 255]],
                                 [[0, 0, 0], [0, 255, 0]]], dtype=np.uint8)).save(self.image)

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_preserves_exhaustive_nearest_colors(self):
        rng = np.random.default_rng(17)
        rgb = rng.integers(0, 256, (24, 19, 3), dtype=np.uint8)
        rgb[3:9] = rgb[0]
        candidates = Palette().candidate_rgb_array()
        diff = rgb_to_lab(rgb.reshape(-1, 3))[:, None, :] - rgb_to_lab(candidates)[None, :, :]
        distance = diff[..., 0] ** 2 + CHROMA_WEIGHT * (diff[..., 1] ** 2 + diff[..., 2] ** 2)
        expected = distance.argmin(axis=1).reshape(rgb.shape[:2])
        np.testing.assert_array_equal(match_to_palette(rgb, candidates, chunk=31), expected)

    def test_alpha_and_exif_orientation(self):
        path = self.root / "transparent.png"
        Image.new("RGBA", (2, 3), (0, 0, 0, 0)).save(path)
        self.assertTrue(np.all(load_image_rgb(path) == 255))
        exif = Image.Exif()
        exif[274] = 6
        path = self.root / "rotated.jpg"
        Image.new("RGB", (2, 3), "red").save(path, exif=exif)
        self.assertEqual(image_size(path), (3, 2))
        self.assertEqual(load_image_rgb(path).shape, (2, 3, 3))

    def test_scaling_materials_and_two_schematics(self):
        progress = []
        result = run_conversion(self.image, width=2, scale=3, make_schematic=True,
                                out_dir=self.root / "out", progress=lambda p, _: progress.append(p))
        self.assertEqual(len(list(result.out_dir.iterdir())), 5)
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 100)
        self.assertEqual(progress, sorted(progress))
        for grid, palette, path, walls in ((result.grid, result.palette, result.schematic, False),
                (result.grid_wall, result.palette_wall, result.schematic_wall, True)):
            _, rows, _ = _stats(grid, palette, scale=3)
            self.assertEqual(sum(info["total"] for _, info in rows), 36)
            _, width, height, columns = read_schematic(path)
            self.assertEqual((width, height), (6, 6))
            for x in range(width):
                for y in range(height):
                    cand = palette.candidates[int(grid[y // 3, x // 3])]
                    expected = ((None, cand.block["wall_id"], 0, cand.paint["id"], 16) if 'wall_id' in cand.block else
                                (cand.block["tile_id"], None, cand.paint["id"], 0, 8))
                    self.assertEqual(columns[x][y], expected)

    def test_cancel_during_export_leaves_no_partial_files(self):
        stop = False

        def progress(value, text):
            nonlocal stop
            if value >= 85:
                stop = True

        output = self.root / "out"
        with self.assertRaises(ConversionCancelled):
            run_conversion(self.image, width=2, make_schematic=True, out_dir=output,
                           progress=progress, cancelled=lambda: stop)
        self.assertEqual(list(output.iterdir()), [])

    def test_repeated_export_does_not_overwrite_and_coating_toggle(self):
        output = self.root / "out"
        first = run_conversion(self.image, width=2, make_schematic=True, out_dir=output, coating=False)
        original = first.schematic.read_bytes()
        second = run_conversion(self.image, width=2, out_dir=output)
        self.assertNotEqual(first.out_dir, second.out_dir)
        self.assertEqual(first.schematic.read_bytes(), original)
        self.assertTrue(all(cell[-1] == 0 for col in read_schematic(first.schematic)[3] for cell in col))
        self.assertFalse(first.processing["coating"])

    def test_long_unicode_name_and_long_vertical_run(self):
        palette = Palette(blocks=[{"tile_id": 1, "rgb": (100, 100, 100)}], paints=[PAINTS[0]])
        grid = np.zeros((3500, 1), dtype=np.int32)
        path = self.root / "long.TEditSch"
        name = "像素图纸" * 40
        write_tedsch(grid, palette, path, name=name, scale=20)
        decoded, width, height, columns = read_schematic(path)
        self.assertEqual(decoded, name)
        self.assertEqual((width, height), (20, 70000))
        self.assertTrue(all(cell == (1, None, 0, 0, 8) for cell in columns[0]))



if __name__ == "__main__":
    unittest.main()
