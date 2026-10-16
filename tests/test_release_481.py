"""独立色库匹配、四版保存和按物体选色/悬停残留的行为回归。"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QToolTip
from PySide6.QtTest import QTest
from terraria_pixel.palette import map_palette
from terraria_pixel.map_colors import match_map
from terraria_pixel.pipeline import prepare_preview, export_preview
from terraria_pixel.history import load_record, HistoryStore, RECORD
from terraria_pixel.editor import EditCanvas
from terraria_pixel.drafts import Draft, save_draft, load_draft
from terraria_pixel.material_library import ASSETS
from test_core import read_schematic


class SplitMapTests(unittest.TestCase):
    def test_both_libraries_and_lookup_match_library_and_exhaustive_rgb(self):
        pixels = np.random.default_rng(481).integers(0, 256, (5, 7, 3), dtype=np.uint8)
        for walls, kind in ((False, 'tile'), (True, 'wall')):
            palette = map_palette(walls=walls)
            raw = (ASSETS / f'library_{kind}.tr').read_bytes()
            count, = struct.unpack_from('<H', raw)
            self.assertEqual(len(palette.candidates), count + (36 if walls else 28) * 19)
            for i, c in enumerate(palette.candidates[:count]):
                self.assertEqual((c.block.get('wall_id', c.block.get('tile_id')), c.paint['id'], int(not walls), *c.rgb),
                                 struct.unpack_from('<HBBBBB', raw, 2 + i * 7))
            colors = palette.candidate_rgb_array().astype(np.int32)
            grid = match_map(pixels, walls=walls)
            canvas = EditCanvas(np.zeros_like(pixels), target='map', indices=grid, palette=palette)
            for y, x in np.ndindex(grid.shape):
                dist = ((colors - pixels[y, x]) ** 2).sum(axis=1)
                expected = int(np.flatnonzero(dist == dist.min())[-1])
                self.assertEqual(int(grid[y, x]), expected)
                from terraria_pixel.material_rules import permitted
                dist[[not permitted(c.block) for c in palette.candidates]] = np.iinfo(np.int32).max
                safe_expected = int(np.flatnonzero(dist == dist.min())[-1])
                self.assertEqual(canvas.nearest_index(pixels[y, x]), safe_expected)

    def test_three_schematics_history_and_map_draft_stay_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.png'
            Image.new('RGB', (3, 2), 'red').save(source)
            result = prepare_preview(source, width=3)
            for grid, palette, key, ident in ((result.grid_map, result.palette_map, 'tile_id', 267),
                                              (result.grid_wall, result.palette_wall, 'wall_id', 330)):
                idx = next(i for i, c in enumerate(palette.candidates) if c.block[key] == ident and c.paint['id'] == 13)
                grid[:] = idx
                grid[0, 0] = -1
            old_tile = result.grid_map.copy()
            canvas = EditCanvas.from_result(result, 'wall')
            canvas.set_cell(2, 1, index=0)
            path = root / 'wall-map.tpdraft'
            save_draft(path, Draft(canvas))
            restored = load_draft(path).canvas
            self.assertEqual(restored.target, 'wall')
            restored.apply_to(result)
            np.testing.assert_array_equal(result.grid_map, old_tile)
            with patch('terraria_pixel.pipeline.match_map', side_effect=AssertionError('must not rematch')):
                saved = export_preview(result, out_dir=root / 'out', make_schematic=True)
                loaded = load_record(saved.out_dir)
            self.assertEqual(len(list(saved.out_dir.glob('*.TEditSch'))), 3)
            for grid, palette, path, wall in ((loaded.grid_map, loaded.palette_map, saved.schematic_map, False),
                                              (loaded.grid_wall, loaded.palette_wall, saved.schematic_wall, True)):
                _, width, height, columns = read_schematic(path)
                for x in range(width):
                    for y in range(height):
                        if grid[y, x] < 0:
                            self.assertEqual(columns[x][y], (None, None, 0, 0, 0))
                            continue
                        c = palette.candidates[int(grid[y, x])]
                        expected = (None, c.block['wall_id'], 0, c.paint['id'], 16) if wall else (c.block['tile_id'], None, c.paint['id'], 0, 0)
                        self.assertEqual(columns[x][y], expected)
            np.testing.assert_array_equal(loaded.grid_wall, result.grid_wall)
            store = HistoryStore(root / 'history.json', root / 'out')
            plan = store.deletion_plan(saved.out_dir)
            self.assertIn(saved.schematic_map, plan['files'])
            self.assertIn(saved.schematic_wall, plan['files'])

    def test_old_format4_mixed_map_preserves_colors_and_does_not_invent_wall_map(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.png'
            Image.new('RGB', (2, 2), 'red').save(source)
            result = prepare_preview(source, width=2)
            result.palette_map = map_palette()
            result.grid_map = match_map(result.processed_rgb[..., :3])
            saved = export_preview(result, out_dir=root / 'out', versions=('fine', 'wall', 'map'))
            meta = json.loads((saved.out_dir / RECORD).read_text(encoding='utf-8'))
            meta['format'] = 4
            meta['palettes'].pop('map_wall', None)
            (saved.out_dir / RECORD).write_text(json.dumps(meta), encoding='utf-8')
            loaded = load_record(saved.out_dir)
            self.assertIsNone(loaded.grid_map_wall)
            self.assertIsNone(loaded.palette_map_wall)
            np.testing.assert_array_equal(loaded.grid_map, result.grid_map)
            np.testing.assert_array_equal(loaded.palette_map.candidate_rgb_array(), result.palette_map.candidate_rgb_array())


class MaterialPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_group_selection_and_tooltip_dismissal(self):
        from terraria_pixel.palette import wall_palette
        from terraria_pixel.editor_window import PixelEditorWindow
        from terraria_pixel.pixels import material_pixels
        palette = wall_palette()
        grid = np.zeros((3, 4), np.int32)
        model = EditCanvas(material_pixels(grid, palette), target='wall', indices=grid, palette=palette)
        editor = PixelEditorWindow(canvas=model)
        editor.resize(1200, 800)
        editor.show()
        self.app.processEvents()
        tree = editor.palette_list
        self.assertEqual(tree.topLevelItemCount(), 292)
        self.assertEqual(tree.topLevelItem(0).childCount(), 19)
        translucent = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if '史莱姆块墙' in tree.topLevelItem(i).text(0))
        self.assertEqual(translucent.toolTip(0), '透光墙')
        ordinary = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == '石墙')
        self.assertEqual(ordinary.toolTip(0), '')
        tree.scrollToItem(ordinary)
        self.app.processEvents()
        pos = tree.visualItemRect(ordinary).center()
        ordinary.setExpanded(False)
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.assertTrue(ordinary.isExpanded())
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.assertFalse(ordinary.isExpanded())
        before = editor.canvas.index
        tree.setCurrentItem(translucent)
        self.assertEqual(editor.canvas.index, before)
        translucent.setExpanded(True)
        white = next(translucent.child(i) for i in range(translucent.childCount()) if translucent.child(i).text(0) == '白漆')
        tree.setCurrentItem(white)
        selected = int(white.data(0, Qt.ItemDataRole.UserRole))
        self.assertEqual(editor.canvas.index, selected)
        self.assertEqual(tuple(editor.canvas.color), palette.candidates[selected].rgb)
        editor.set_tool('fill')
        self.assertEqual(editor.canvas.index, selected)

        def hover(item):
            tree.scrollToItem(item)
            self.app.processEvents()
            pos = tree.visualItemRect(item).center()
            event = QHelpEvent(QEvent.Type.ToolTip, pos, tree.viewport().mapToGlobal(pos))
            QApplication.sendEvent(tree.viewport(), event)
            self.app.processEvents()

        hover(translucent)
        self.assertTrue(QToolTip.isVisible())
        self.assertEqual(QToolTip.text(), '透光墙')
        tree.verticalScrollBar().setValue(tree.verticalScrollBar().value() + 50)
        QTest.qWait(400)
        self.assertFalse(QToolTip.isVisible())
        hover(translucent)
        editor.search.setText('石墙')
        QTest.qWait(400)
        self.assertFalse(QToolTip.isVisible())
        self.assertEqual(editor.canvas.index, selected)  # 搜索不偷偷改变选色
        ordinary = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount()) if tree.topLevelItem(i).text(0) == '石墙')
        hover(ordinary)
        QTest.qWait(400)
        self.assertFalse(QToolTip.isVisible())
        editor.grab().save(str(Path(__file__).resolve().parents[2] / '.tmp/desktop-verification/v481-grouped-materials.png'))
        editor.close()


if __name__ == '__main__':
    unittest.main()
