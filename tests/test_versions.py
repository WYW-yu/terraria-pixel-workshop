"""两版本保存及旧作品/草稿的无损读取。"""
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
import numpy as np
from PIL import Image
from terraria_pixel.pipeline import prepare_preview, export_preview
from terraria_pixel.history import RECORD, DATA, load_record
from terraria_pixel.drafts import Draft, save_draft, load_draft
from terraria_pixel.editor import EditCanvas


class VersionCompatibilityTests(unittest.TestCase):
    def test_old_record_preserves_block_and_wall_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            Image.new('RGB', (4, 3), (160, 80, 40)).save(source)
            result = export_preview(prepare_preview(source, width=4), out_dir=root / 'out')
            meta = json.loads((result.out_dir / RECORD).read_text(encoding='utf-8'))
            self.assertEqual(meta['format'], 5)
            self.assertEqual(set(meta['palettes']), {'fine', 'wall', 'map'})
            with np.load(result.out_dir / DATA) as data:
                self.assertNotIn('simple', data.files)
            fine, wall = meta['palettes']['fine'], meta['palettes']['wall']
            meta.update(format=2, palettes=[fine, fine, wall], versions=['simple'])
            meta['processing']['simple_k'] = 3
            (result.out_dir / RECORD).write_text(json.dumps(meta), encoding='utf-8')
            with patch('terraria_pixel.pipeline.match_to_palette', side_effect=AssertionError('must not rematch')):
                loaded = load_record(result.out_dir)
            self.assertEqual(loaded.versions, ('fine', 'wall'))
            self.assertNotIn('simple_k', loaded.processing)
            for a, b in ((result.grid, loaded.grid), (result.grid_wall, loaded.grid_wall)):
                np.testing.assert_array_equal(a, b)
            np.testing.assert_array_equal(result.palette_wall.candidate_rgb_array(), loaded.palette_wall.candidate_rgb_array())

    def test_old_material_draft_imports_as_block_without_rematching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            Image.new('RGB', (2, 2), 'red').save(source)
            canvas = EditCanvas.from_result(prepare_preview(source, width=2), 'fine')
            current = root / 'current.tpdraft'
            save_draft(current, Draft(canvas))
            with ZipFile(current) as z:
                files = {n: z.read(n) for n in z.namelist()}
            settings = json.loads(files['settings.json'])
            settings.update(target='simple', allowed_indices=[int(canvas.indices[0, 0])])
            files['settings.json'] = json.dumps(settings).encode()
            old = root / 'old.tpdraft'
            with ZipFile(old, 'w') as z:
                for name, data in files.items():
                    z.writestr(name, data)
            loaded = load_draft(old).canvas
            self.assertEqual(loaded.target, 'fine')
            np.testing.assert_array_equal(loaded.rgb, canvas.rgb)
            np.testing.assert_array_equal(loaded.indices, canvas.indices)
