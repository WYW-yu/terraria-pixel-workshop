"""选色面板的数据层测试：颜色换算、HEX 解析、经典色板、历史记录。"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from terraria_pixel.color_panel import (ColorHistory, classic_swatches, hex_text, hsv_to_rgb,
                                        parse_hex, rgb_to_hsv)


class TestColorMath(unittest.TestCase):
    def test_hsv_round_trip(self):
        for rgb in ((255, 0, 0), (0, 128, 255), (18, 22, 34), (250, 246, 220), (128, 128, 128)):
            hue, saturation, value = rgb_to_hsv(rgb)
            back = hsv_to_rgb(hue, saturation, value)
            for got, want in zip(back, rgb):
                self.assertLessEqual(abs(got - want), 1, (rgb, back))

    def test_primary_hues(self):
        self.assertAlmostEqual(rgb_to_hsv((255, 0, 0))[0], 0, delta=1)
        self.assertAlmostEqual(rgb_to_hsv((0, 255, 0))[0], 120, delta=1)
        self.assertAlmostEqual(rgb_to_hsv((0, 0, 255))[0], 240, delta=1)

    def test_hex_text_and_parse(self):
        self.assertEqual(hex_text((18, 34, 56)), "#122238")
        self.assertEqual(parse_hex("#122238"), (18, 34, 56))
        self.assertEqual(parse_hex("122238"), (18, 34, 56))
        self.assertEqual(parse_hex("#abc"), (170, 187, 204))
        self.assertIsNone(parse_hex("#12"))
        self.assertIsNone(parse_hex("zzzzzz"))

    def test_classic_swatches_shape(self):
        colors = classic_swatches(12, 5)
        self.assertEqual(len(colors), 60)
        self.assertTrue(all(len(c) == 3 for c in colors))
        self.assertTrue(all(0 <= v <= 255 for c in colors for v in c))
        # 最后一行应是灰阶
        for rgb in colors[48:]:
            self.assertLessEqual(max(rgb) - min(rgb), 1, rgb)


class TestColorHistory(unittest.TestCase):
    def test_dedupe_and_limit(self):
        history = ColorHistory(limit=3)
        history.push((1, 2, 3))
        history.push((4, 5, 6))
        history.push((1, 2, 3))            # 重复项提到最前
        self.assertEqual(history.items[0], (1, 2, 3))
        self.assertEqual(len(history.items), 2)
        for i in range(5):
            history.push((i, i, i))
        self.assertEqual(len(history.items), 3)
        history.clear()
        self.assertEqual(history.items, [])

    def test_clamps_out_of_range(self):
        history = ColorHistory()
        history.push((-5, 300, 128))
        self.assertEqual(history.items[0], (0, 255, 128))


if __name__ == "__main__":
    unittest.main()
