"""选区填色与不同粗细画笔的范围、透明层和撤销语义。"""
import unittest
import numpy as np
from terraria_pixel.editor import EditCanvas
from terraria_pixel.palette import Palette
from terraria_pixel.pixels import material_pixels


class SelectionBrushTests(unittest.TestCase):
    def test_fill_rectangle_covers_mixed_colors_once_and_undo_redo(self):
        original = np.random.default_rng(411).integers(0, 256, (8, 10, 3), dtype=np.uint8)
        canvas = EditCanvas(original)
        self.assertEqual(canvas.fill_rectangle((2, 1, 6, 4), rgb=(17, 33, 91)), 20)
        expected = original.copy()
        expected[1:5, 2:7] = (17, 33, 91)
        np.testing.assert_array_equal(canvas.rgb, expected)
        canvas.undo()
        np.testing.assert_array_equal(canvas.rgb, original)
        self.assertFalse(canvas.can_undo)
        canvas.redo()
        np.testing.assert_array_equal(canvas.rgb, expected)
        self.assertEqual(canvas.fill_rectangle((2, 1, 6, 4), rgb=(17,33,91)), 0)

    def test_transparent_rectangle_and_opaque_brush(self):
        canvas = EditCanvas.blank(8, 8)
        canvas.fill_rectangle((1, 1, 5, 5), rgb=(0,0,0,0))
        self.assertTrue(np.all(canvas.rgb[1:6, 1:6, 3] == 0))
        canvas.brush(3, 3, size=3, rgb=(10,20,30))
        self.assertTrue(np.all(canvas.rgb[2:5, 2:5] == (10,20,30,255)))
        canvas.undo()
        self.assertTrue(np.all(canvas.rgb[1:6, 1:6, 3] == 0))
        canvas.undo()
        self.assertTrue(np.all(canvas.rgb == 255))

    def test_material_rectangle_and_brush_preserve_indices_and_alpha(self):
        for target, key in [('fine','tile_id'), ('wall','wall_id'), ('map','tile_id')]:
            with self.subTest(target=target):
                palette = Palette(blocks=[{key:1,'rgb':(80,80,80)}, {key:2,'rgb':(200,200,200)}],
                                  paints=[{'id':0}])
                grid = np.zeros((8,8),np.int32)
                canvas = EditCanvas(material_pixels(grid, palette), target=target, indices=grid, palette=palette)
                canvas.fill_rectangle((1,1,4,3), index=1)
                self.assertTrue(np.all(canvas.indices[1:4,1:5] == 1))
                self.assertTrue(np.all(canvas.rgb[1:4,1:5] == (200,200,200)))
                canvas.brush(3,3,size=3,index=-1)
                self.assertTrue(np.all(canvas.indices[2:5,2:5] == -1))
                self.assertTrue(np.all(canvas.rgb[2:5,2:5,3] == 0))
                canvas.undo()
                self.assertFalse(np.any(canvas.indices < 0))
                canvas.undo()
                self.assertTrue(np.all(canvas.indices == 0))

    def test_brush_sizes_and_selection_clipping_single_stroke_undo(self):
        for size in (1,2,3,8,64):
            canvas = EditCanvas.blank(80,80)
            self.assertEqual(canvas.brush(40,40,size,rgb=(0,0,0)),size*size)
            self.assertEqual(np.count_nonzero(np.all(canvas.rgb == 0,axis=-1)),size*size)
        canvas = EditCanvas.blank(10,10)
        canvas.begin_stroke()
        for x in range(1,8):
            canvas.brush(x,4,5,rgb=(0,0,0),bounds=(2,3,6,5))
        canvas.end_stroke()
        expected = np.full((10,10,3),255,np.uint8)
        expected[3:6,2:7] = 0
        np.testing.assert_array_equal(canvas.rgb,expected)
        canvas.undo()
        self.assertTrue(np.all(canvas.rgb == 255))
        self.assertFalse(canvas.can_undo)
        self.assertEqual(canvas.brush(0,0,3,rgb=(0,0,0)),4)

    def test_existing_connected_fill_stays_connected(self):
        canvas = EditCanvas.blank(6,4)
        canvas.fill_rectangle((2,0,2,3),rgb=(0,0,0))
        self.assertEqual(canvas.fill(0,1,rgb=(9,8,7),bounds=(0,0,5,3)),8)
        self.assertTrue(np.all(canvas.rgb[:,3:] == 255))


if __name__ == '__main__':
    unittest.main()
