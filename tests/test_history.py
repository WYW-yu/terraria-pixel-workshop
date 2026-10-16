"""预览不落盘、选择性导出和历史读取的行为回归。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terraria_pixel.pipeline import prepare_preview, export_preview, run_conversion, ConversionCancelled
from terraria_pixel.history import HistoryStore, load_record


def legacy_result(source, output):
    from terraria_pixel.pipeline import Result, PREVIEW_NAMES
    import json
    directory = output / "old-work"
    directory.mkdir(parents=True)
    for name in PREVIEW_NAMES[:2]:
        Image.open(source).save(directory / name)
    (directory / "转换设置.json").write_text(json.dumps({"width":10}), encoding="utf-8")
    (directory / "材料清单.html").write_text("legacy report",encoding="utf-8")
    (directory / "材料清单.txt").write_text("泰拉瑞拉像素画 · 材料清单\n图纸名 : sample\n图片 : 测试图片.png",encoding="utf-8")
    return Result(out_dir=directory)


class PreviewHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "测试图片.png"
        Image.fromarray(np.random.default_rng(3).integers(0, 256, (8, 10, 3), dtype=np.uint8)).save(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def test_preview_creates_no_files_and_export_uses_cached_colors(self):
        before = list(self.root.iterdir())
        preview = prepare_preview(self.source, width=10)
        self.assertEqual(list(self.root.iterdir()), before)
        self.assertIsNone(preview.out_dir)
        self.source.unlink()
        with patch("terraria_pixel.pipeline.match_to_palette", side_effect=AssertionError("must not recalculate")), \
             patch("terraria_pixel.pipeline.load_image_pixels", side_effect=AssertionError("must not read source")):
            result = export_preview(preview, out_dir=self.root / "out", versions=("wall",), make_schematic=True)
        self.assertIsNone(result.schematic)
        self.assertTrue(result.schematic_wall.is_file())
        self.assertFalse(any("简单版" in p.name for p in result.out_dir.iterdir()))
        self.assertEqual({p.name for p in result.out_dir.iterdir()}, 
                         {"作品记录.json", "作品数据.npz", result.schematic_wall.name})
        restored = load_record(result.out_dir)
        self.assertEqual(restored.versions, ("wall",))
        self.assertIsNone(preview.out_dir)

    def test_history_restores_materials_and_reexports_without_source(self):
        preview = prepare_preview(self.source, width=10, scale=2, dither="bayer")
        saved = export_preview(preview, out_dir=self.root / "out", versions=("fine",), make_schematic=True)
        self.source.unlink()
        store = HistoryStore(self.root / "历史记录.json", self.root / "out")
        store.remember(saved.out_dir)
        reopened_store = HistoryStore(store.path, self.root / "elsewhere")
        self.assertEqual(reopened_store.entries()[0]["directory"], saved.out_dir)
        with patch("terraria_pixel.pipeline.match_to_palette", side_effect=AssertionError("must not recalculate")):
            restored = load_record(saved.out_dir)
            second = export_preview(restored, out_dir=self.root / "second", versions=("fine",), make_schematic=True)
        self.assertEqual(saved.schematic.read_bytes(), second.schematic.read_bytes())
        self.assertFalse(list(second.out_dir.glob("*.png")))
        for grid, other in ((preview.grid, restored.grid),
                            (preview.grid_wall, restored.grid_wall)):
            np.testing.assert_array_equal(grid, other)
        for a, b in ((preview.palette, restored.palette), (preview.palette_wall, restored.palette_wall)):
            np.testing.assert_array_equal(a.candidate_rgb_array(), b.candidate_rgb_array())
        self.assertIsNotNone(restored.source_preview)
        self.assertEqual(restored.processing, preview.processing)

    def test_legacy_results_remain_viewable(self):
        old = legacy_result(self.source, self.root / "legacy")
        loaded = load_record(old.out_dir)
        self.assertIsNone(loaded.grid)
        self.assertEqual(set(loaded.saved_images), {"fine", "wall"})
        self.assertEqual(len(HistoryStore(self.root / "index.json", self.root / "legacy").entries()), 1)

    def test_empty_selection_and_cancel_do_not_publish(self):
        preview = prepare_preview(self.source, width=10)
        output = self.root / "out"
        with self.assertRaises(ValueError):
            export_preview(preview, out_dir=output, versions=())
        self.assertFalse(output.exists())
        stop = False

        def progress(value, text):
            nonlocal stop
            if value >= 86:
                stop = True

        with self.assertRaises(ConversionCancelled):
            export_preview(preview, out_dir=output, progress=progress, cancelled=lambda: stop)
        self.assertEqual(list(output.iterdir()), [])

    def test_delete_generated_files_preserves_original_and_unrelated_files(self):
        preview = prepare_preview(self.source, width=10)
        # 删除行为使用可持久保存的三种素材方案；临时冰块拒绝导出另有专项测试。
        saved = export_preview(preview, out_dir=self.root / "out", versions=('fine', 'wall', 'map'), make_schematic=True)
        store = HistoryStore(self.root / "index.json", self.root / "out")
        store.remember(saved.out_dir)
        other = saved.out_dir / "其他图纸.TEditSch"
        other.write_bytes(b"do not delete")
        notes = saved.out_dir / "我的备注.txt"
        notes.write_text("keep", encoding="utf-8")
        nested = saved.out_dir / "其他文件"
        nested.mkdir()
        (nested / "像素画预览.png").write_bytes(b"keep")
        original = self.source.read_bytes()
        plan = store.deletion_plan(saved.out_dir)
        self.assertNotIn(other, plan["files"])
        self.assertNotIn(notes, plan["files"])
        deleted, errors = store.delete_records([saved.out_dir])
        self.assertEqual(errors, [])
        self.assertEqual(deleted, [saved.out_dir])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(other.read_bytes(), b"do not delete")
        self.assertTrue((nested / "像素画预览.png").exists())
        self.assertFalse(saved.schematic.exists())
        self.assertFalse((saved.out_dir / "作品数据.npz").exists())
        self.assertEqual(HistoryStore(store.path, store.default_root).entries(), [])

    def test_delete_all_new_and_legacy_removes_empty_work_folders(self):
        output = self.root / "out"
        preview = prepare_preview(self.source, width=10)
        new = export_preview(preview, out_dir=output, versions=("wall",), make_schematic=True)
        old = legacy_result(self.source, output)
        store = HistoryStore(self.root / "index.json", output)
        store.remember(new.out_dir)
        directories = [entry["directory"] for entry in store.entries()]
        self.assertEqual(len(directories), 2)
        deleted, errors = store.delete_records(directories)
        self.assertEqual(errors, [])
        self.assertEqual(len(deleted), 2)
        self.assertFalse(new.out_dir.exists())
        self.assertFalse(old.out_dir.exists())
        self.assertTrue(output.is_dir())
        self.assertTrue(self.source.is_file())
        self.assertEqual(store.entries(), [])

    def test_delete_rejects_unrecognized_folder(self):
        store = HistoryStore(self.root / "index.json", self.root)
        important = self.root / "important"
        important.mkdir()
        (important / "像素画预览.png").write_bytes(b"not a generated work")
        deleted, errors = store.delete_records([important])
        self.assertEqual(deleted, [])
        self.assertTrue(errors)
        self.assertTrue((important / "像素画预览.png").exists())

    def test_delete_failure_keeps_history_for_retry(self):
        preview = prepare_preview(self.source, width=10)
        saved = export_preview(preview, out_dir=self.root / "out")
        store = HistoryStore(self.root / "index.json", self.root / "out")
        store.remember(saved.out_dir)
        with patch.object(Path, "unlink", side_effect=PermissionError("in use")):
            deleted, errors = store.delete_records([saved.out_dir])
        self.assertFalse(deleted)
        self.assertTrue(errors)
        self.assertEqual(store.entries()[0]["directory"], saved.out_dir)

    def test_partial_delete_can_retry_and_preserves_source_inside_work(self):
        saved = export_preview(prepare_preview(self.source, width=10), out_dir=self.root / "out",
                               versions=('fine', 'wall', 'map'), make_schematic=True)
        store = HistoryStore(self.root / "index.json", self.root / "out")
        store.remember(saved.out_dir)
        original_unlink = Path.unlink

        def locked(path, *args, **kwargs):
            if path == saved.schematic_wall:
                raise PermissionError("locked schematic")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", locked):
            deleted, errors = store.delete_records([saved.out_dir])
        self.assertFalse(deleted)
        self.assertTrue(errors)
        self.assertTrue((saved.out_dir / "作品记录.json").is_file())
        self.assertEqual(store.entries()[0]["directory"], saved.out_dir)
        deleted, errors = store.delete_records([saved.out_dir])
        self.assertFalse(errors)
        self.assertEqual(deleted, [saved.out_dir])
        self.assertFalse(saved.out_dir.exists())

        preview = prepare_preview(self.source, width=10)
        new = export_preview(preview, out_dir=self.root / "out")
        from terraria_pixel.history import RECORD
        import json
        inside_source = new.out_dir / "像素化原色.png"
        inside_source.write_bytes(self.source.read_bytes())
        marker = new.out_dir / RECORD
        meta = json.loads(marker.read_text(encoding="utf-8"))
        meta["source_path"] = str(inside_source)
        marker.write_text(json.dumps(meta), encoding="utf-8")
        contents = inside_source.read_bytes()
        deleted, errors = store.delete_records([new.out_dir])
        self.assertFalse(errors)
        self.assertEqual(inside_source.read_bytes(), contents)
        self.assertFalse(store.entries())

    def test_delete_does_not_include_files_created_after_confirmation(self):
        preview = prepare_preview(self.source, width=10)
        saved = export_preview(preview, out_dir=self.root / "out", versions=("wall",))
        store = HistoryStore(self.root / "index.json", self.root / "out")
        plan = store.deletion_plan(saved.out_dir)
        extra = saved.out_dir / "像素画预览.png"
        extra.write_bytes(b"new export after confirmation")
        deleted, errors = store.delete_records([saved.out_dir], confirmed_plans=[plan])
        self.assertFalse(deleted)
        self.assertTrue(errors)
        self.assertTrue((saved.out_dir / "作品记录.json").is_file())
        self.assertEqual(extra.read_bytes(), b"new export after confirmation")


if __name__ == "__main__":
    unittest.main()
