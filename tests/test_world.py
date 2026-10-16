"""世界段保留、RLE切分、家具保护、透明格和原子保存回归。"""
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from terraria_pixel.formats import ConversionCancelled
from terraria_pixel.palette import Palette
from terraria_pixel.schematic import serialize_tile, _write_bit_array, _write_string, FRAMES
from terraria_pixel.world import load_world, write_world, read_info


def fixture(path, width=8, height=12, special=False, version=326):
    header = bytearray(struct.pack('<i', version) + b'relogic\x02' + bytes(12))
    header.extend(struct.pack('<h', 11) + bytes(44))
    _write_bit_array(header, FRAMES)
    metadata = bytearray()
    _write_string(metadata, '中文测试世界')
    _write_string(metadata, '123')
    metadata.extend(bytes(24) + struct.pack('<i4iii', 8123, 0, width * 16, 0, height * 16, height, width))
    tiles = bytearray()
    for x in range(width):
        if special and x == 1:
            # 两字节墙ID + 墙漆 + 微光液体 + 四种电线 + 斜坡 + 回声/夜明。
            record = bytes([1 | 2 | 4 | 8, 1 | 2 | 4 | 8 | 32, 1 | 8 | 16 | 32 | 64 | 128, 30,
                            1, 13, 74, 26, 255, 1])
        elif special and x == 3:
            record = serialize_tile(True, 21, 0, 0, 0, 0, 0)
        else:
            record = serialize_tile(True, 1, 0, 0, 0, 1, 0)
        tiles.extend(bytes([record[0] | 128]) + record[1:] + struct.pack('<h', height - 1))
    sections = [bytes(metadata), bytes(tiles)] + [bytes([i, 9, 8, 7]) for i in range(2, 10)]
    footer = bytearray(b'\x01')
    _write_string(footer, '中文测试世界')
    footer.extend(struct.pack('<i', 8123))
    sections.append(bytes(footer))
    offset = len(header)
    for i, section in enumerate(sections):
        struct.pack_into('<i', header, 26 + 4 * i, offset)
        offset += len(section)
    path.write_bytes(header + b''.join(sections))
    return path


def independent_tiles(document):
    """用流读取逐字段解码，不调用产品的_run或column索引。"""
    info = document.info
    stream = io.BytesIO(document.data)
    stream.seek(info.pointers[1])

    def integer(size=1, signed=False):
        raw = stream.read(size)
        assert len(raw) == size
        return int.from_bytes(raw, 'little', signed=signed)

    columns = []
    for x in range(info.width):
        col = []
        while len(col) < info.height:
            h1 = integer()
            h2 = integer() if h1 & 1 else 0
            h3 = integer() if h2 & 1 else 0
            h4 = integer() if h3 & 1 else 0
            tile = integer(2 if h1 & 32 else 1) if h1 & 2 else None
            frame = stream.read(4) if tile is not None and info.frames[tile] else None
            paint = integer() if tile is not None and h3 & 8 else 0
            wall = integer() if h1 & 4 else 0
            wall_paint = integer() if h1 & 4 and h3 & 16 else 0
            liquid = integer() if h1 & 24 else 0
            if h3 & 64:
                wall += integer() * 256
            repeat = integer() if h1 >> 6 == 1 else integer(2, True) if h1 >> 6 >= 2 else 0
            item = (tile, wall, paint, wall_paint, h2 & 254, h3 & 230, h4, liquid, frame)
            col.extend([item] * (repeat + 1))
        assert len(col) == info.height
        columns.append(col)
    assert stream.tell() == info.pointers[2]
    return columns


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = fixture(self.root / '原世界.wld', special=True)
        self.world = load_world(self.source, overview=False)
        self.palette = Palette(blocks=[{'tile_id': 267, 'name_zh': '玻璃', 'rgb': (100, 100, 100)},
                                       {'wall_id': 330, 'name_zh': '墙', 'rgb': (50, 50, 50)}],
                               paints=[{'id': 13, 'name_zh': '红漆', 'rgb': (255, 0, 0)}])

    def tearDown(self):
        self.temp.cleanup()

    def test_split_rle_keep_all_other_sections_and_transparent_cells(self):
        before = independent_tiles(self.world)
        digest = self.source.read_bytes()
        grid = np.array([[0, 1], [-1, 0]], np.int32)
        target = self.root / '另存.wld'
        progress = []
        write_world(self.world, grid, self.palette, target, x=0, y=3, scale=1,
                    progress=lambda p, _: progress.append(p))
        after_world = load_world(target, overview=False)
        after = independent_tiles(after_world)
        for x in range(8):
            for y in range(12):
                if (x, y) in ((0, 3), (1, 4)):
                    self.assertEqual(after[x][y][:4], (267, 0, 13, 0))
                    self.assertEqual(after[x][y][6], 8)
                elif (x, y) == (1, 3):
                    self.assertEqual(after[x][y][:4], (None, 330, 0, 13))
                    self.assertEqual(after[x][y][6], 16)
                else:
                    self.assertEqual(after[x][y], before[x][y], (x, y))
        for a, b in zip(self.world.info.pointers[2:], after_world.info.pointers[2:]):
            self.assertEqual(self.world.data[a:a + 4], after_world.data[b:b + 4])
        self.assertEqual(self.world.data[self.world.info.pointers[2]:], after_world.data[after_world.info.pointers[2]:])
        self.assertEqual(self.world.data[self.world.info.pointers[0]:self.world.info.pointers[1]],
                         after_world.data[after_world.info.pointers[0]:after_world.info.pointers[1]])
        for x in range(2, 8):
            a, b = self.world.columns[x:x + 2]
            c, d = after_world.columns[x:x + 2]
            self.assertEqual(self.world.data[a:b], after_world.data[c:d])
        self.assertEqual(self.source.read_bytes(), digest)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 100)

    def test_scale_boundary_and_coating_off(self):
        grid = np.array([[0, -1]], np.int32)
        target = self.root / '边界.wld'
        write_world(self.world, grid, self.palette, target, x=4, y=10, scale=2, coating=False)
        after = independent_tiles(load_world(target, overview=False))
        before = independent_tiles(self.world)
        for x in range(8):
            for y in range(12):
                if x in (4, 5) and y in (10, 11):
                    self.assertEqual(after[x][y][:4], (267, 0, 13, 0))
                    self.assertEqual(after[x][y][6], 0)
                else:
                    self.assertEqual(after[x][y], before[x][y])

    def test_invalid_inputs_and_furniture_never_publish(self):
        grid = np.array([[0]], np.int32)
        for options in ({'x': -1, 'y': 0}, {'x': 8, 'y': 0}, {'x': 0, 'y': 12},
                        {'x': 3, 'y': 0}, {'x': 0, 'y': 0, 'scale': 0}, {'x': .5, 'y': 0}):
            with self.subTest(options=options):
                path = self.root / '无效.wld'
                with self.assertRaises(ValueError):
                    write_world(self.world, grid, self.palette, path, **options)
                self.assertFalse(path.exists())
        original = self.source.read_bytes()
        with self.assertRaises(ValueError):
            write_world(self.world, grid, self.palette, self.source, x=0, y=0)
        self.assertEqual(self.source.read_bytes(), original)
        for index in (-2, 2, -1):
            with self.assertRaises(ValueError):
                write_world(self.world, np.array([[index]]), self.palette, self.root / '非法.wld', x=0, y=0)
        ice = Palette(blocks=[{'tile_id': 127, 'name_zh': '临时冰块', 'rgb': (0, 0, 0)}], paints=self.palette.paints)
        with self.assertRaisesRegex(ValueError, '127'):
            write_world(self.world, grid, ice, self.root / '冰.wld', x=0, y=0)

    def test_cancel_and_source_change_leave_no_output_or_temporary(self):
        target = self.root / '取消.wld'
        stopped = False

        def cancel_late(value, _):
            nonlocal stopped
            if value >= 60:
                stopped = True

        with self.assertRaises(ConversionCancelled):
            write_world(self.world, np.array([[0]]), self.palette, target, x=0, y=0,
                        cancelled=lambda: stopped, progress=cancel_late)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.pixel-world-*')))
        self.source.write_bytes(self.source.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, '发生了变化'):
            write_world(self.world, np.array([[0]]), self.palette, target, x=0, y=0)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('.pixel-world-*')))

    def test_publication_failure_keeps_existing_file(self):
        target = self.root / '目标.wld'

        def competing_file(value, _):
            if value == 99:
                target.write_bytes(b'other writer')

        with self.assertRaises(FileExistsError):
            write_world(self.world, np.array([[0]]), self.palette, target, x=0, y=0, progress=competing_file)
        self.assertEqual(target.read_bytes(), b'other writer')
        self.assertFalse(list(self.root.glob('.pixel-world-*')))

    def test_bad_headers_truncation_and_column_overflow_rejected(self):
        original = self.source.read_bytes()
        corruptions = [original[:10], original[:-1], b'bad!' + original[4:]]
        wrong_version = bytearray(original)
        struct.pack_into('<i', wrong_version, 0, 327)
        corruptions.append(wrong_version)
        overflow = bytearray(original)
        struct.pack_into('<h', overflow, self.world.columns[1] - 2, 100)
        corruptions.append(overflow)
        pointer = bytearray(original)
        struct.pack_into('<i', pointer, 26 + 4 * 2, len(original) + 20)
        corruptions.append(pointer)
        for i, data in enumerate(corruptions):
            path = self.root / f'坏文件{i}.wld'
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                load_world(path, overview=False)

    def test_version269_and_large_rle(self):
        path = fixture(self.root / '旧格式.wld', width=1, height=1200, version=269)
        world = load_world(path, overview=False)
        target = self.root / '长列.wld'
        write_world(world, np.zeros((600, 1), np.int32), self.palette, target, x=0, y=300)
        after = independent_tiles(load_world(target, overview=False))
        self.assertEqual(len(after[0]), 1200)
        self.assertTrue(all(t[0] == 267 for t in after[0][300:900]))
        self.assertEqual(after[0][299][0], 1)
        self.assertEqual(after[0][900][0], 1)

    def test_material_requiring_furniture_frames_is_rejected(self):
        for tile in (423, 520):
            palette = Palette(blocks=[{'tile_id': tile, 'name_zh': str(tile), 'rgb': (0, 0, 0)}], paints=self.palette.paints)
            target = self.root / f'物块{tile}.wld'
            with self.assertRaisesRegex(ValueError, '独立家具帧'):
                write_world(self.world, np.zeros((4, 1), np.int32), palette, target, x=0, y=0)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
