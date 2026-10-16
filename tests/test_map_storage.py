"""无损存储、旧格式兼容、损坏文件和解压大小限制。"""
import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from terraria_pixel import map_storage as storage
from terraria_pixel.map_colors import lookup


class MapStorageTests(unittest.TestCase):
    def setUp(self):
        storage.candidate_records.cache_clear()

    def tearDown(self):
        storage.candidate_records.cache_clear()

    def test_all_tables_match_original_hash_without_disk_expansion(self):
        audit = json.loads((Path(__file__).resolve().parents[1] / 'tools/map_compression.json').read_text())
        before = {p.name: p.stat().st_size for p in storage.ASSETS.iterdir() if p.is_file()}
        for kind, expected in audit.items():
            table = storage.table_bytes(kind)
            raw = struct.pack('<H', storage.MAP_COUNTS[kind]) + storage.candidate_records(kind) + table
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected['original_sha256'])
            self.assertEqual(len(table), storage.TABLE_BYTES)
        self.assertEqual(before, {p.name: p.stat().st_size for p in storage.ASSETS.iterdir() if p.is_file()})
        self.assertFalse(lookup(False).flags.writeable)

    def test_small_split_and_legacy_formats_return_identical_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            records = b'\0' * 7
            content = bytes(range(32))
            path = folder / 'library_tile.tr'
            sidecar = folder / 'library_tile.lut.z'
            with patch.object(storage, 'ASSETS', folder), patch.object(storage, 'MAP_COUNTS', {'tile': 1}), patch.object(storage, 'TABLE_BYTES', 32):
                path.write_bytes(struct.pack('<H', 1) + records + content)
                self.assertEqual(storage.table_bytes('tile'), content)
                path.write_bytes(struct.pack('<H', 1) + records)
                sidecar.write_bytes(zlib.compress(content))
                self.assertEqual(storage.table_bytes('tile'), content)
                self.assertEqual(storage.candidate_records('tile'), records)

    def test_corrupt_missing_trailing_and_oversized_data_raise_clear_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'library_tile.tr').write_bytes(struct.pack('<H', 1) + b'\0' * 7)
            sidecar = folder / 'library_tile.lut.z'
            with patch.object(storage, 'ASSETS', folder), patch.object(storage, 'MAP_COUNTS', {'tile': 1}), patch.object(storage, 'TABLE_BYTES', 32):
                for invalid in (b'', b'bad', zlib.compress(b'0' * 31), zlib.compress(b'0' * 33), zlib.compress(b'0' * 32) + b'trailing', zlib.compress(b'0' * 32)[:-1]):
                    sidecar.write_bytes(invalid)
                    with self.assertRaisesRegex(ValueError, '损坏或缺失'):
                        storage.table_bytes('tile')
                sidecar.unlink()
                with self.assertRaisesRegex(ValueError, '损坏或缺失'):
                    storage.table_bytes('tile')

    def test_incorrect_candidate_header_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(storage, 'ASSETS', folder), patch.object(storage, 'MAP_COUNTS', {'tile': 1}):
                for data in (b'', struct.pack('<H', 2) + b'\0' * 7, struct.pack('<H', 1) + b'\0' * 8):
                    (folder / 'library_tile.tr').write_bytes(data)
                    with self.assertRaisesRegex(ValueError, '不完整'):
                        storage.candidate_records('tile')


if __name__ == '__main__':
    unittest.main()
