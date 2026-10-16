"""新增材料的精确地图匹配、高ID写入、禁用素材与旧草稿兼容。"""
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np

from terraria_pixel.material_library import ASSETS, data
from terraria_pixel.palette import map_palette, mixed_palette
from terraria_pixel.map_colors import match_map
from terraria_pixel.material_rules import permitted, FALLING_EFFECT_TILES
from terraria_pixel.schematic import write_tedsch
from terraria_pixel.world import load_world, write_world
from terraria_pixel.editor import EditCanvas
from terraria_pixel.drafts import Draft, save_draft, load_draft
from terraria_pixel.pixels import material_pixels
from test_core import read_schematic
from test_world import fixture, independent_tiles

ROOT = ASSETS.parent


class Release413Tests(unittest.TestCase):
    def test_added_map_colors_match_exhaustive_candidates_including_ties(self):
        palette = map_palette(walls=False)
        colors = palette.candidate_rgb_array().astype(np.int32)
        queries = np.concatenate((colors[5871::19], np.random.default_rng(413).integers(0, 256, (128, 3))))
        result = match_map(queries.astype(np.uint8)[None], walls=False)[0]
        for q, actual in zip(queries, result):
            distances = np.sum((colors - q) ** 2, axis=1)
            self.assertEqual(actual, np.flatnonzero(distances == distances.min())[-1])
        self.assertTrue(np.any(result >= 5871), '新增候选必须实际参与匹配')

    def test_all_additions_have_separate_complete_color_models(self):
        facts = json.loads((ROOT / 'tools/material_additions_1458.json').read_text(encoding='utf-8'))['materials']
        self.assertEqual(sum(f['kind'] == 'tile' for f in facts), 28)
        self.assertEqual(sum(f['kind'] == 'wall' for f in facts), 36)
        entries = {(('wall', e['material']['wall_id']) if 'wall_id' in e['material'] else ('tile', e['material']['tile_id'])): e for e in data()['materials']}
        for fact in facts:
            entry = entries[fact['kind'], fact['id']]
            self.assertEqual(entry['map_rgb'], fact['map_rgb'])
            for field in ('placed_colors',) + (('actuated_colors',) if fact['kind'] == 'tile' else ()):
                colors = np.asarray(entry[field])
                self.assertEqual(colors.shape, (31, 3))
                self.assertTrue(np.all((colors >= 0) & (colors <= 255)))
            self.assertEqual(np.asarray(entry['material']['placed_lab']).shape, (31, 3))
            self.assertTrue(np.isfinite(entry['material']['placed_lab']).all())
        for ident in FALLING_EFFECT_TILES:
            self.assertFalse(permitted({'tile_id': ident}))
        self.assertTrue(permitted({'tile_id': 189}), '普通云不能误禁用')

    def test_added_materials_roundtrip_schematic_and_world(self):
        palette = mixed_palette()
        additions = data()['materials'][-64:]
        indices = []
        for e in additions:
            block = e['material']
            if not permitted(block):
                continue
            key = 'wall_id' if 'wall_id' in block else 'tile_id'
            indices.append([next(i for i, c in enumerate(palette.candidates)
                                 if c.block.get(key) == block[key] and c.paint['id'] == pid)
                            for pid in (13, 26, 28, 30)])
        grid = np.array(indices, np.int32).T
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schematic = root / '新增材料.TEditSch'
            write_tedsch(grid, palette, schematic, name='新增材料', coating=True)
            columns = read_schematic(schematic)[3]
            original = fixture(root / '原世界.wld', width=grid.shape[1]+2, height=8)
            before = original.read_bytes()
            destination = root / '新世界.wld'
            write_world(load_world(original, overview=False), grid, palette, destination, x=1, y=1, coating=True)
            cells = independent_tiles(load_world(destination, overview=False))
            for y, x in np.ndindex(grid.shape):
                c = palette.candidates[grid[y, x]]
                wall = 'wall_id' in c.block
                expected = (None, c.block['wall_id'], 0, c.paint['id']) if wall else (c.block['tile_id'], None, c.paint['id'], 0)
                self.assertEqual(columns[x][y][:4], expected)
                world_expected = (None, expected[1], 0, expected[3]) if wall else (expected[0], 0, expected[2], 0)
                self.assertEqual(cells[x+1][y+1][:4], world_expected)
                self.assertEqual(cells[x+1][y+1][6], 16 if wall else 8)
                self.assertEqual(cells[x+1][y+1][5] & 6, 0 if wall else 4)
            self.assertEqual(original.read_bytes(), before)

    def test_removed_wall_map_draft_keeps_saved_pixels(self):
        palette = map_palette(walls=True)
        grid = np.array([[0, 21], [-1, 90]], np.int32)
        pixels = material_pixels(grid, palette)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'old.tpdraft'
            save_draft(path, Draft(EditCanvas(pixels, target='map', indices=grid, palette=palette)))
            with ZipFile(path) as archive:
                files = {n: archive.read(n) for n in archive.namelist()}
            meta = json.loads(files['settings.json'])
            meta['target'] = 'map_wall'
            files['settings.json'] = json.dumps(meta).encode('utf-8')
            with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
            restored = load_draft(path).canvas
            self.assertEqual(restored.target, 'pixel')
            np.testing.assert_array_equal(restored.rgb, pixels)


if __name__ == '__main__':
    unittest.main()
