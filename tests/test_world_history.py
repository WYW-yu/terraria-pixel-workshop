"""世界导入记录使用独立作品快照；不依赖原图片/世界，不删除世界。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from terraria_pixel.history import HistoryStore, load_record, save_world_import_record
from terraria_pixel.palette import Palette, PAINTS
from terraria_pixel.pipeline import Result


def sample_result():
    mixed = Palette(blocks=[dict(tile_id=1, name_zh='石块', rgb=(120, 120, 120)),
                            dict(wall_id=4, name_zh='木墙', rgb=(150, 100, 70))], paints=[PAINTS[0]])
    wall = Palette(blocks=[mixed.blocks[1]], paints=[PAINTS[0]])
    rgba = np.array([[[10, 20, 30, 255], [1, 2, 3, 0]],
                     [[100, 150, 200, 255], [90, 80, 70, 255]]], np.uint8)
    return Result(width=2, height=2, scale=2, name='作品', source_name='已删除的原图.png',
        original_size=(20, 20), source_preview=rgba.copy(), processed_rgb=rgba,
        processing=dict(coating=False),
        grid=np.array([[1, -1], [0, 1]], np.int32),
        grid_wall=np.array([[0, -1], [0, 0]], np.int32),
        grid_map=np.array([[0, -1], [1, 0]], np.int32),
        palette=mixed, palette_wall=wall, palette_map=mixed)


class WorldHistoryTests(unittest.TestCase):
    def test_each_version_restores_exact_snapshot_without_source_or_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = sample_result()
            store = HistoryStore(root / 'index.json', root / 'output')
            for version in ('fine', 'wall', 'map'):
                with patch('terraria_pixel.pipeline.match_to_palette', side_effect=AssertionError('recomputed')):
                    saved = save_world_import_record(result, root / 'output', root / 'world.wld',
                        source=root / 'original.wld', version=version, x=3, y=5, coating=True)
                    store.remember(saved.out_dir)
                    restored = load_record(saved.out_dir)
                self.assertEqual(restored.versions, (version,))
                self.assertEqual({p.name for p in saved.out_dir.iterdir()}, {'作品记录.json', '作品数据.npz'})
                for field in ('processed_rgb', 'source_preview', 'grid', 'grid_wall', 'grid_map'):
                    np.testing.assert_array_equal(getattr(restored, field), getattr(result, field))
                for field in ('palette', 'palette_wall', 'palette_map'):
                    np.testing.assert_array_equal(getattr(restored, field).candidate_rgb_array(),
                                                  getattr(result, field).candidate_rgb_array())
                details = restored.processing['world_import']
                self.assertEqual((details['version'], details['x'], details['y'], details['coating']),
                                 (version, 3, 5, True))
                self.assertFalse(result.processing.get('world_import'))
                self.assertIsNone(result.out_dir)
            self.assertEqual(len(store.entries()), 3)
            self.assertIn('导入世界', store.entries()[0]['title'])

    def test_deleting_record_does_not_delete_world_even_in_work_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = save_world_import_record(sample_result(), root / 'output', root / 'world.wld',
                source=root / 'world.wld', version='map', x=1, y=2, coating=False, overwrite=True)
            world = saved.out_dir / 'world.wld'
            world.write_bytes(b'world must remain')
            store = HistoryStore(root / 'index.json', root / 'output')
            store.remember(saved.out_dir)
            deleted, errors = store.delete_records([saved.out_dir])
            self.assertFalse(errors)
            self.assertEqual(deleted, [saved.out_dir])
            self.assertEqual(world.read_bytes(), b'world must remain')
            self.assertFalse(store.entries())

    def test_cli_world_import_also_saves_history_without_world_backup(self):
        import main
        from test_world import fixture
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = fixture(root / 'source.wld')
            original = source.read_bytes()
            target = root / 'target.wld'
            with patch('terraria_pixel.pipeline.prepare_preview', return_value=sample_result()), \
                 patch.object(main, '__file__', str(root / 'main.py')):
                code = main.cli_main(['missing-source.png', '--world', str(source),
                    '--world-out', str(target), '--world-version', 'map', '--out', str(root / 'output')])
            self.assertEqual(code, 0)
            self.assertTrue(target.is_file())
            self.assertEqual(source.read_bytes(), original)
            store = HistoryStore(root / '历史记录.json', root / 'output')
            restored = load_record(store.entries()[0]['directory'])
            self.assertEqual(restored.versions, ('map',))
            np.testing.assert_array_equal(restored.grid_map, sample_result().grid_map)
            self.assertFalse(list(root.glob('*.bak')))


if __name__ == '__main__':
    unittest.main()
