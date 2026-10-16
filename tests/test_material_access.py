"""Independent item/world ID examples and obtainable-wall export regressions."""
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from terraria_pixel.material_access import access_data, item_id_for, wall_replacement
from terraria_pixel.material_library import data
from terraria_pixel.material_rules import permitted, validate_grid
from terraria_pixel.palette import Palette, PAINTS, mixed_palette, wall_palette, map_palette
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.schematic import write_tedsch
from terraria_pixel.world import load_world, write_world
from terraria_pixel.materials import _stats
from test_core import read_schematic
from test_world import fixture, independent_tiles


class MaterialAccessTests(unittest.TestCase):
    def test_item_ids_resolve_to_world_wall_ids_not_equal_numbers(self):
        examples = {183: 3082, 184: 3088, 247: 4487, 250: 4490, 275: 3273,
                    304: 3340, 305: 3341, 310: 3346, 311: 3348,
                    17: 135, 18: 138, 19: 140, 39: 618, 75: 768}
        blocks = {b['wall_id']: b for b in wall_palette().blocks}
        for wall_id, item_id in examples.items():
            self.assertEqual(blocks[wall_id]['item_id'], item_id)
            self.assertEqual(item_id_for(blocks[wall_id]), item_id)
            self.assertNotEqual(item_id, wall_id)
        # Even an old record's incorrect annotation cannot point at a different wall.
        self.assertEqual(item_id_for(dict(wall_id=17, item_id=5418)), 135)
        self.assertIsNone(item_id_for(dict(wall_id=178, item_id=3082)))
        self.assertEqual(item_id_for(dict(tile_id=194, item_id=766)), 154)

    def test_natural_aliases_keep_all_craftable_counterparts(self):
        walls = {b['wall_id']: b for b in wall_palette().blocks}
        aliases = access_data()['wall_aliases']
        self.assertEqual(len(aliases), 71)
        for source, target in aliases.items():
            self.assertFalse(permitted(walls[int(source)]))
            self.assertTrue(permitted(walls[target]))
            self.assertIsNone(walls[int(source)]['item_id'])
            self.assertIsNotNone(item_id_for(walls[target]))
        self.assertEqual(wall_replacement(178), 183)
        self.assertEqual(wall_replacement(48), 250)
        self.assertEqual(wall_replacement(349), 1)
        # Obtainable unsafe variants from Shimmer remain selectable.
        for ident in (2, 7, 8, 9, 62, 87, 94, 95, 96, 97, 98, 99, 187, 216, 244):
            self.assertTrue(permitted(walls[ident]), ident)
            self.assertIsNotNone(item_id_for(walls[ident]))
        self.assertEqual(sum(permitted(b) for b in walls.values()), 292)

    def test_alias_keeps_target_color_data_instead_of_relabeling_source(self):
        entries = {e['material']['wall_id']: e for e in data()['materials'] if 'wall_id' in e['material']}
        for source, target in ((178, 183), (48, 250), (13, 177)):
            self.assertEqual(wall_replacement(source), target)
            for palette in (wall_palette(), map_palette(walls=True)):
                c = next(c for c in palette.candidates if c.block.get('wall_id') == target and c.paint['id'] == 0)
                expected = entries[target]['map_rgb'] if c.block['color_model'].startswith('pixel-map') else entries[target]['placed_colors'][0]
                self.assertEqual(c.rgb, tuple(expected))
        self.assertNotEqual(entries[13]['placed_colors'], entries[177]['placed_colors'])

    def test_special_materials_blocked_but_normal_states_still_allowed(self):
        for ident in (272, 273, 350):
            self.assertFalse(permitted(dict(wall_id=ident)))
        for ident in (504, 668):
            self.assertFalse(permitted(dict(tile_id=ident)))
        for ident in (*range(255, 262), 477, 512, 517, 535, 537, 540, 557, 626, 628):
            self.assertTrue(permitted(dict(tile_id=ident)))

    def test_all_three_generated_versions_and_both_writers_use_actual_placeable_walls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'source.png'
            rng = np.random.default_rng(52)
            Image.fromarray(rng.integers(0, 256, (12, 16, 3), dtype=np.uint8)).save(image)
            result = prepare_preview(image, width=16, sampling='nearest')
            for grid, palette in ((result.grid, result.palette), (result.grid_wall, result.palette_wall), (result.grid_map, result.palette_map)):
                validate_grid(grid, palette)
                for index in np.unique(grid):
                    b = palette.candidates[index].block
                    if 'wall_id' in b:
                        self.assertIsNotNone(item_id_for(b))
                        self.assertIsNone(wall_replacement(b['wall_id']))
            # Exercise every usable wall, including IDs above 255, with paint and transparency.
            palette = wall_palette()
            indices = [i for i, c in enumerate(palette.candidates) if permitted(c.block) and c.paint['id'] == 28]
            grid = np.array([indices + [-1]], np.int32)
            source = fixture(root / 'source.wld', width=grid.shape[1] + 2, height=3)
            before = source.read_bytes()
            schematic = root / 'walls.TEditSch'
            write_tedsch(grid, palette, schematic, name='walls', walls_only=True, coating=True)
            destination = root / 'new.wld'
            write_world(load_world(source, overview=False), grid, palette, destination, x=1, y=1)
            sch = read_schematic(schematic)[3]
            world = independent_tiles(load_world(destination, overview=False))
            for x, index in enumerate(indices):
                wall_id = palette.candidates[index].block['wall_id']
                self.assertEqual(sch[x][0][:4], (None, wall_id, 0, 28))
                self.assertEqual(world[x+1][1][:4], (None, wall_id, 0, 28))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(sch[-1][0], (None, None, 0, 0, 0))

    def test_writers_reject_special_and_natural_ids_before_creating_output(self):
        palette = mixed_palette()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = load_world(fixture(root / 'source.wld', width=3, height=3), overview=False)
            for key, ident in (('wall_id', 178), ('wall_id', 272), ('wall_id', 350), ('tile_id', 504), ('tile_id', 668)):
                index = next(i for i, c in enumerate(palette.candidates) if c.block.get(key) == ident)
                grid = np.array([[index]], np.int32)
                for writer, path in ((lambda p: write_tedsch(grid, palette, p, name='bad'), root/'bad.TEditSch'),
                                     (lambda p: write_world(source, grid, palette, p, x=1, y=1), root/'bad.wld')):
                    with self.assertRaises(ValueError):
                        writer(path)
                    self.assertFalse(path.exists())

    def test_material_summary_corrects_old_item_annotation(self):
        palette = Palette(blocks=[dict(wall_id=183, item_id=999, rgb=(100, 100, 100),
                                     name='Marble', name_zh='大理石墙')], paints=[PAINTS[0]])
        rows, blocks, _ = _stats(np.array([[0, 0]], np.int32), palette)
        self.assertEqual(blocks[0][0][3], 3082)
        self.assertEqual(blocks[0][1]['total'], 2)


if __name__ == '__main__':
    unittest.main()
