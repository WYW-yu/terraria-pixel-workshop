"""跨颜色模型、既有色库 查询表、混合图纸及旧作品/新草稿互通。"""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from terraria_pixel.palette import wall_palette, map_palette
from terraria_pixel.map_colors import match_map, nearest_rgb
from terraria_pixel.material_library import ASSETS
from terraria_pixel.pipeline import prepare_preview, export_preview
from terraria_pixel.history import load_record, RECORD, HistoryStore
from terraria_pixel.editor import EditCanvas
from terraria_pixel.drafts import Draft, save_draft, load_draft
from test_core import read_schematic


class MapVersionTests(unittest.TestCase):
    def test_candidate_records_match_every_library_record(self):
        raw = (ASSETS / 'library_all.tr').read_bytes()
        count, = struct.unpack_from('<H', raw)
        palette = map_palette()
        self.assertEqual(len(palette.candidates), count + 64 * 19)
        for i, c in enumerate(palette.candidates[:count]):
            expected = struct.unpack_from('<HBBBBB', raw, 2 + i * 7)
            self.assertEqual((c.block.get('wall_id', c.block.get('tile_id')), c.paint['id'],
                              int('tile_id' in c.block), *c.rgb), expected)

    def test_lookup_and_editing_use_rgb_last_tie(self):
        palette = map_palette()
        colors = palette.candidate_rgb_array().astype(np.int32)
        rgb = np.random.default_rng(273).integers(0, 256, (8, 8, 3), dtype=np.uint8)
        indices = match_map(rgb)
        canvas = EditCanvas(np.zeros_like(rgb), target='map', indices=indices, palette=palette)
        for y, x in np.ndindex(indices.shape):
            distances = ((colors - rgb[y, x]) ** 2).sum(axis=1)
            expected = int(np.flatnonzero(distances == distances.min())[-1])
            self.assertEqual(int(indices[y, x]), expected)
            from terraria_pixel.material_rules import permitted
            distances[[not permitted(c.block) for c in palette.candidates]] = np.iinfo(np.int32).max
            safe_expected = int(np.flatnonzero(distances == distances.min())[-1])
            self.assertEqual(canvas.nearest_index(rgb[y, x]), safe_expected)
        self.assertEqual(nearest_rgb((0, 0, 0), [[0, 0, 0], [255, 255, 255], [0, 0, 0]]), 2)

    def test_same_material_has_independent_map_and_placed_rgb(self):
        def color(palette, pid):
            return next(c.rgb for c in palette.candidates if c.block.get('wall_id') == 155 and c.paint['id'] == pid)
        self.assertEqual(color(map_palette(), 13), (247, 0, 0))
        self.assertEqual(color(wall_palette(), 13), (232, 88, 88))
        self.assertEqual(color(map_palette(), 26), (247, 247, 247))
        self.assertEqual(color(wall_palette(), 26), (254, 254, 254))

    def test_map_export_history_draft_and_mixed_tile_wall_schematic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'source.png'
            Image.new('RGB', (3, 2), 'red').save(image)
            result = prepare_preview(image, width=3)
            palette = result.palette_map
            self.assertTrue(any('tile_id' in b for b in palette.blocks))
            self.assertTrue(any('wall_id' in b for b in palette.blocks))
            def index(key, ident, paint):
                return next(i for i, c in enumerate(palette.candidates) if c.block.get(key) == ident and c.paint['id'] == paint)
            tile = index('tile_id', 267, 30)
            wall = index('wall_id', 330, 29)
            result.grid_map = np.array([[tile, wall, -1], [wall, tile, wall]], np.int32)
            canvas = EditCanvas.from_result(result, 'map')
            draft = root / 'map.tpdraft'
            save_draft(draft, Draft(canvas))
            restored_canvas = load_draft(draft).canvas
            self.assertEqual(restored_canvas.target, 'map')
            np.testing.assert_array_equal(restored_canvas.rgb, canvas.rgb)
            restored_canvas.set_cell(2, 0, index=tile)
            before_fine = result.grid.copy()
            restored_canvas.apply_to(result)
            np.testing.assert_array_equal(result.grid, before_fine)
            with patch('terraria_pixel.pipeline.match_to_palette', side_effect=AssertionError('no rematch')):
                saved = export_preview(result, out_dir=root / 'out', versions=('map',), make_schematic=True)
                loaded = load_record(saved.out_dir)
            np.testing.assert_array_equal(loaded.grid_map, result.grid_map)
            np.testing.assert_array_equal(loaded.palette_map.candidate_rgb_array(), palette.candidate_rgb_array())
            self.assertEqual(loaded.versions, ('map',))
            self.assertEqual(saved.schematic_map.name, 'source-地图版.TEditSch')
            _, width, height, columns = read_schematic(saved.schematic_map)
            self.assertEqual((width, height), (3, 2))
            for x in range(width):
                for y in range(height):
                    c = palette.candidates[int(result.grid_map[y, x])]
                    expected = (None, c.block['wall_id'], 0, c.paint['id'], 0) if 'wall_id' in c.block else (c.block['tile_id'], None, c.paint['id'], 0, 0)
                    self.assertEqual(columns[x][y], expected)
            store = HistoryStore(root / 'index.json', root / 'out')
            self.assertIn(saved.schematic_map, store.deletion_plan(saved.out_dir)['files'])

    def test_format3_record_does_not_invent_map_or_rematch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'source.png'
            Image.new('RGB', (2, 2), 'red').save(image)
            saved = export_preview(prepare_preview(image, width=2), out_dir=root / 'out')
            meta = json.loads((saved.out_dir / RECORD).read_text(encoding='utf-8'))
            meta.update(format=3, versions=['fine', 'wall'])
            meta['palettes'].pop('map')
            meta['palettes'].pop('map_wall', None)
            (saved.out_dir / RECORD).write_text(json.dumps(meta), encoding='utf-8')
            with patch('terraria_pixel.pipeline.match_map', side_effect=AssertionError('no rematch')):
                loaded = load_record(saved.out_dir)
            self.assertIsNone(loaded.grid_map)
            self.assertIsNone(loaded.palette_map)
            np.testing.assert_array_equal(loaded.grid, saved.grid)
            with self.assertRaisesRegex(ValueError, '旧作品'):
                export_preview(loaded, out_dir=root / 'second', versions=('map',))

    def test_map_ignores_material_dither_and_white_alpha_compositing(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / 'alpha.png'
            rgb = np.array([[[240, 240, 247, 128], [232, 88, 88, 0]]], np.uint8)
            Image.fromarray(rgb).save(image)
            result = prepare_preview(image, width=2, sampling='nearest', dither='bayer')
            self.assertEqual(int(result.grid_map[0, 0]), int(match_map(rgb[..., :3])[0, 0]))
            self.assertEqual(int(result.grid_map[0, 1]), -1)

    def test_generation_uses_both_tile_and_wall_map_colors_with_safety(self):
        from terraria_pixel.material_rules import permitted
        palette = map_palette()
        # 同色候选取最后一个；从安全色库挑出能分别命中物块和墙的颜色。
        last_by_color = {c.rgb: i for i, c in enumerate(palette.candidates) if permitted(c.block)}
        queries = []
        for wall in (False, True):
            queries.extend(color for color, i in last_by_color.items()
                           if ('wall_id' in palette.candidates[i].block) == wall)
        rgb = np.array(queries[::max(1, len(queries) // 128)], np.uint8)[None]
        colors = palette.candidate_rgb_array().astype(np.int32)
        allowed = np.array([permitted(c.block) for c in palette.candidates])
        expected = []
        for pixel in rgb[0]:
            distances = np.sum((colors - pixel) ** 2, axis=1)
            distances[~allowed] = np.iinfo(np.int32).max
            expected.append(int(np.flatnonzero(distances == distances.min())[-1]))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'mixed.png'
            Image.fromarray(rgb).save(image)
            result = prepare_preview(image, width=rgb.shape[1], sampling='nearest')
            np.testing.assert_array_equal(result.grid_map[0], expected)
            self.assertEqual(result.processing['map_material_scope'], 'mixed-tile-wall')
            kinds = {'wall' if 'wall_id' in result.palette_map.candidates[i].block else 'tile' for i in expected}
            self.assertEqual(kinds, {'tile', 'wall'})
            # 自动生成的混合地图必须能按各自类型写入图纸和世界。
            saved = export_preview(result, out_dir=root / 'out', versions=('map',), make_schematic=True)
            columns = read_schematic(saved.schematic_map)[3]
            from test_world import fixture, independent_tiles
            from terraria_pixel.world import load_world, write_world
            source = fixture(root / 'source.wld', width=rgb.shape[1] + 2, height=3)
            target = root / 'target.wld'
            write_world(load_world(source, overview=False), result.grid_map, result.palette_map,
                        target, x=1, y=1, coating=True)
            cells = independent_tiles(load_world(target, overview=False))
            for x, index in enumerate(expected):
                c = result.palette_map.candidates[index]
                wall = 'wall_id' in c.block
                schematic_cell = ((None, c.block['wall_id'], 0, c.paint['id']) if wall else
                                  (c.block['tile_id'], None, c.paint['id'], 0))
                self.assertEqual(columns[x][0][:4], schematic_cell)
                world_cell = ((None, c.block['wall_id'], 0, c.paint['id']) if wall else
                              (c.block['tile_id'], 0, c.paint['id'], 0))
                self.assertEqual(cells[x + 1][1][:4], world_cell)
                self.assertEqual(cells[x + 1][1][6], 16 if wall else 8)

    def test_temporary_ice_export_fails_instead_of_silently_losing_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.png'
            Image.new('RGB', (1, 1), 'red').save(source)
            result = prepare_preview(source, width=1)
            i = next(i for i, c in enumerate(result.palette_map.candidates) if c.block.get('tile_id') == 127)
            result.grid_map[:] = i
            with self.assertRaisesRegex(ValueError, '临时冰块'):
                export_preview(result, out_dir=root / 'out', versions=('map',), make_schematic=True)
            self.assertEqual(list((root / 'out').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
