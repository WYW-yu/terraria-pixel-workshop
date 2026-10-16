"""用实际发行EXE导入真实世界副本，比较逐格数据、段内容和错误路径。"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.world import load_world, material_version
from terraria_pixel.palette import map_palette
from terraria_pixel.material_rules import permitted
from terraria_pixel.history import HistoryStore, load_record
from test_world import independent_tiles

exe, source = map(lambda p: Path(p).resolve(), sys.argv[1:3])
original = source.read_bytes()
document = load_world(source, overview=False)
original_cells = independent_tiles(document)
with tempfile.TemporaryDirectory(prefix='frozen-world-', dir=exe.parents[3] / '.tmp') as temporary:
    root = Path(temporary)
    # EXE会保存历史索引，使用隔离副本，避免改写用户的实际历史记录。
    app = root / 'app'
    app.mkdir()
    shutil.copy2(exe, app / exe.name)
    shutil.copytree(exe.parent / '_internal', app / '_internal')
    exe = app / exe.name
    source_image = root / '导入图片.png'
    palette = map_palette()
    last_by_color = {c.rgb: i for i, c in enumerate(palette.candidates) if permitted(c.block)}
    tile_rgb = next(rgb for rgb, i in last_by_color.items() if 'tile_id' in palette.candidates[i].block)
    rgba = np.array([[list(tile_rgb) + [255], [0, 0, 0, 0]],
                     [[0, 255, 0, 255], [255, 255, 0, 255]]], np.uint8)
    Image.fromarray(rgba).save(source_image)
    expected = prepare_preview(source_image, width=2, scale=2, sampling='nearest')
    assert {'tile' if 'tile_id' in expected.palette_map.candidates[i].block else 'wall'
            for i in expected.grid_map.flat if i >= 0} == {'tile', 'wall'}
    history_root = root / 'history'
    base = [str(exe), str(source_image), '--width', '2', '--scale', '2', '--sampling', 'nearest',
            '--world', str(source), '--out', str(history_root)]
    for version in ('fine', 'wall', 'map'):
        output = root / (version + '.wld')
        command = base + ['--world-out', str(output), '--world-version', version, '--world-x', '2000', '--world-y', '50']
        process = subprocess.run(command, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode == 0, (version, process.returncode)
        saved = load_world(output, overview=False)
        cells = independent_tiles(saved)
        grid, palette = material_version(expected, version)
        for x in range(document.info.width):
            for y in range(document.info.height):
                gx, gy = (x - 2000) // 2, (y - 50) // 2
                if not (0 <= gx < 2 and 0 <= gy < 2) or grid[gy, gx] < 0:
                    assert cells[x][y] == original_cells[x][y], (version, x, y)
                else:
                    c = palette.candidates[int(grid[gy, gx])]
                    wall = 'wall_id' in c.block
                    expected_cell = (None, c.block['wall_id'], 0, c.paint['id']) if wall else (c.block['tile_id'], 0, c.paint['id'], 0)
                    assert cells[x][y][:4] == expected_cell
                    assert cells[x][y][6] == ((16 if wall else 8) if version in ('fine', 'wall') else 0)
                    assert cells[x][y][5] & 6 == (0 if wall else 4), '虚化标记或致动器状态错误'
        assert saved.data[saved.info.pointers[2]:] == document.data[document.info.pointers[2]:]
        entry = HistoryStore(app / '历史记录.json', history_root).entries()[0]
        record = load_record(entry['directory'])
        assert record.versions == (version,)
        assert record.processing['world_import']['path'] == str(output.resolve())
        np.testing.assert_array_equal(record.processed_rgb, expected.processed_rgb)
        np.testing.assert_array_equal(material_version(record, version)[0], grid)
        print(f'Frozen {version}: every cell / alpha / coatings / other sections verified', flush=True)
        assert subprocess.run(command, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW).returncode == 1
    for output, options in ((source, []), (root / '越界.wld', ['--world-x', str(document.info.width)])):
        command = base + ['--world-out', str(output)] + options
        assert subprocess.run(command, timeout=40, creationflags=subprocess.CREATE_NO_WINDOW).returncode == 1
    assert not (root / '越界.wld').exists()
    assert not list(root.glob('.pixel-world-*'))
    assert not list(root.rglob('*.bak'))
    assert len(HistoryStore(app / '历史记录.json', history_root).entries()) == 3
    assert source.read_bytes() == original
    assert not (root / '作品记录.json').exists()
print('Frozen world import: three versions + exact history + existing file refusal + bounds + source unchanged OK')
