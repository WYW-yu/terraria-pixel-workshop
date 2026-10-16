"""草稿原像素恢复、材料恢复、输入错误和保存失败保护。"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from terraria_pixel.drafts import Draft, save_draft, load_draft, import_image, fingerprint
from terraria_pixel.editor import EditCanvas
from terraria_pixel.palette import Palette


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_pixels_and_tools_roundtrip_without_applying(self):
        canvas = EditCanvas.blank(13, 9)
        canvas.set_cell(4, 5, rgb=(12, 34, 56))
        path = self.root / '中文草稿.tpdraft'
        save_draft(path, Draft(canvas, (219, 22, 22), 'fill', ((1, 2, 3),), (2, 3, 8, 7)))
        restored = load_draft(path)
        np.testing.assert_array_equal(restored.canvas.rgb, canvas.rgb)
        self.assertTrue(canvas.dirty, 'Saving must not mark edits as applied to a result')
        self.assertEqual(restored.color, (219, 22, 22))
        self.assertEqual(restored.history, ((1, 2, 3),))
        self.assertEqual(restored.tool, 'fill')
        self.assertEqual(restored.selection, (2, 3, 8, 7))

    def test_material_snapshot(self):
        palette = Palette(blocks=[{'tile_id': 1, 'name_zh': '石块', 'name': 'Stone', 'rgb': (100, 100, 100)},
                                  {'tile_id': 2, 'name_zh': '泥土', 'name': 'Dirt', 'rgb': (80, 60, 40)}],
                          paints=[{'id': 0, 'name_zh': '无喷漆', 'rgb': (255, 255, 255)}])
        indices = np.array([[0, 1], [1, 0]], np.int32)
        canvas = EditCanvas(palette.candidate_rgb_array()[indices], 'fine', indices, palette)
        canvas.set_cell(0, 1, index=0)
        canvas.set_cell(1, 0, index=0)
        path = self.root / 'materials.tpdraft'
        save_draft(path, Draft(canvas, (100, 100, 100)))
        restored = load_draft(path).canvas
        np.testing.assert_array_equal(restored.rgb, canvas.rgb)
        np.testing.assert_array_equal(restored.indices, canvas.indices)
        self.assertEqual(restored.palette.describe(1), palette.describe(1))

    def test_image_import_keeps_pixels_and_size(self):
        pixels = np.arange(11 * 7 * 3, dtype=np.uint8).reshape(7, 11, 3)
        path = self.root / 'drawing.png'
        Image.fromarray(pixels).save(path)
        np.testing.assert_array_equal(import_image(path).canvas.rgb, pixels)

    def test_failed_save_preserves_previous_file(self):
        path = self.root / 'draft.tpdraft'
        draft = Draft(EditCanvas.blank(8, 8))
        save_draft(path, draft)
        old = path.read_bytes()
        draft.canvas.set_cell(1, 1, rgb=(1, 2, 3))
        with patch('terraria_pixel.drafts.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                save_draft(path, draft)
        self.assertEqual(path.read_bytes(), old)
        self.assertFalse(list(self.root.glob('.draft-*')))

    def test_bad_draft_and_oversized_array_header_rejected(self):
        path = self.root / 'bad.tpdraft'
        path.write_bytes(b'not a zip')
        with self.assertRaises(ValueError):
            load_draft(path)
        save_draft(path, Draft(EditCanvas.blank(8, 8)))
        with ZipFile(path) as z:
            pixels = z.read('pixels.png')
            meta = json.loads(z.read('settings.json'))
        meta['selection'] = [-1, 0, 7, 7]
        with ZipFile(path, 'w') as z:
            z.writestr('pixels.png', pixels)
            z.writestr('settings.json', json.dumps(meta))
        with self.assertRaises(ValueError):
            load_draft(path)
        meta['selection'] = None
        meta['target'] = 'fine'
        meta['blocks'] = []
        meta['paints'] = []
        meta['candidates'] = [dict(block=dict(tile_id=1, name='Stone', name_zh='石块'),
                                  paint=dict(id=0, name_zh='无喷漆'), rgb=(255, 255, 255))]
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(header, dict(shape=(10**9, 10**9), fortran_order=False, descr='<i4'))
        with ZipFile(path, 'w') as z:
            z.writestr('pixels.png', pixels)
            z.writestr('settings.json', json.dumps(meta))
            z.writestr('indices.npy', header.getvalue())
        with self.assertRaises(ValueError):
            load_draft(path)

    def test_fingerprint_changes_and_undo_restores(self):
        canvas = EditCanvas.blank(6, 4)
        before = fingerprint(canvas)
        canvas.set_cell(1, 1, rgb=(1, 2, 3))
        self.assertNotEqual(before, fingerprint(canvas))
        canvas.undo()
        self.assertEqual(before, fingerprint(canvas))


if __name__ == '__main__':
    unittest.main()
