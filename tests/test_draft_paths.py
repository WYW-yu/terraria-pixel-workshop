"""草稿发现与损坏索引回归，避免两个入口显示不同内容。"""
import json
import tempfile
import unittest
from pathlib import Path
from terraria_pixel.draft_paths import draft_folder, list_drafts, recent_drafts, remember_draft


class DraftPathTests(unittest.TestCase):
    def test_default_legacy_external_and_uppercase(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            current = draft_folder(base) / '当前.TPDRAFT'
            legacy = base / '草稿' / '旧草稿.tpdraft'
            external = base / 'other' / '外部.tpdraft'
            for path in (current, legacy, external):
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(b'draft fixture')
            remember_draft(base, current)
            remember_draft(base, external)
            (draft_folder(base) / '其他.txt').write_text('ignore')
            self.assertEqual(set(list_drafts(base)), {current, legacy, external})
            external.unlink()
            self.assertEqual(set(list_drafts(base)), {current, legacy})

    def test_wrong_index_structure_does_not_hide_default_drafts(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            folder = draft_folder(base)
            path = folder / '未完成.tpdraft'
            path.write_bytes(b'draft fixture')
            for invalid in ({str(path): 'bad'}, str(path), None, 123):
                (folder / '最近草稿.json').write_text(json.dumps(invalid), encoding='utf-8')
                self.assertEqual(recent_drafts(base), [])
                self.assertEqual(list_drafts(base), [path])
