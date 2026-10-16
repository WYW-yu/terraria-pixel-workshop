"""独立运行发行 EXE，比较真实文件输出，并检查打包 GUI 启动。"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
sys.path.insert(0, str(project / 'tests'))
from terraria_pixel.pipeline import run_conversion

exe = Path(sys.argv[1]).resolve()
assert exe.is_file()
with tempfile.TemporaryDirectory(prefix="release-check-", dir=project.parent / ".tmp") as temporary:
    root = Path(temporary)
    # 非规则网格，包含平滑渐变与色相变化。
    y, x = np.mgrid[:48, :64]
    rgb = np.stack([x * 4, y * 5, (x + y) * 2], axis=-1).clip(0, 255).astype(np.uint8)
    source = root / "发行验证.png"
    Image.fromarray(rgb).resize((512, 384), Image.Resampling.BICUBIC).save(source)
    for mode in ("none", "bayer", "floyd"):
        target = root / mode
        process = subprocess.run([str(exe), str(source), "--width", "64", "--scale", "2",
            "--color-limit", "16", "--dither", mode,
            "--no-open", "--out", str(target)], timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode == 0, process.returncode
        packed = next(target.iterdir())
        expected = run_conversion(source, width=64, scale=2, color_limit=16,
            dither=mode, make_schematic=False, out_dir=root / "expected")
        for reference in expected.out_dir.iterdir():
            actual = packed / reference.name
            assert actual.is_file(), reference.name
            if reference.suffix == ".json":
                a=json.loads(reference.read_text(encoding="utf-8")); b=json.loads(actual.read_text(encoding="utf-8"))
                a.pop("created"); b.pop("created")
                assert a == b
            elif reference.suffix == ".npz":
                with np.load(reference, allow_pickle=False) as a, np.load(actual, allow_pickle=False) as b:
                    assert a.files == b.files
                    for key in a.files: np.testing.assert_array_equal(a[key], b[key])
            elif reference.suffix == ".TEditSch":
                assert reference.read_bytes() == actual.read_bytes(), (mode, reference.name)
        print(f"Packaged {mode}: three material snapshots and settings equivalent to source")

    transparent = np.zeros((3, 4, 4), np.uint8)
    transparent[1, 2] = (255, 0, 0, 255)
    alpha_source = root / 'transparent.png'
    Image.fromarray(transparent).save(alpha_source)
    alpha_output = root / 'alpha-output'
    alpha_run = subprocess.run([str(exe), str(alpha_source), '--width', '4', '--sampling', 'nearest', '--schematic', '--out', str(alpha_output)], timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert alpha_run.returncode == 0
    alpha_work = next(alpha_output.iterdir())
    with np.load(alpha_work / '作品数据.npz') as data:
        np.testing.assert_array_equal(data['processed'], transparent)
        assert np.count_nonzero(data['fine'] >= 0) == 1
        assert np.count_nonzero(data['wall'] >= 0) == 1
        assert np.count_nonzero(data['map'] >= 0) == 1
        assert 'map_wall' not in data.files
    from test_core import read_schematic
    from terraria_pixel.history import load_record
    restored = load_record(alpha_work)
    paths = sorted(alpha_work.glob('*.TEditSch'))
    assert len(paths) == 3
    for name, grid, palette in (('transparent',restored.grid,restored.palette),
            ('transparent-背景墙版',restored.grid_wall,restored.palette_wall),
            ('transparent-地图版',restored.grid_map,restored.palette_map)):
        path = alpha_work / (name + '.TEditSch')
        tiles = read_schematic(path)[3]
        assert tiles[0][0] == (None, None, 0, 0, 0)
        candidate = palette.candidates[int(grid[1, 2])]
        wall = 'wall_id' in candidate.block
        expected = (None, candidate.block['wall_id'], 0, candidate.paint['id']) if wall else (candidate.block['tile_id'],None,candidate.paint['id'],0)
        assert tiles[2][1][:4] == expected
    wide_source = root / 'wide.png'
    Image.new('RGB', (5001, 2), 'red').save(wide_source)
    for diagram in (False, True):
        destination = root / ('wide-diagram' if diagram else 'wide-data')
        command = [str(exe), str(wide_source), '--width', '5001', '--out', str(destination)]
        if diagram: command.append('--schematic')
        check = subprocess.run(command, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert check.returncode == (1 if diagram else 0)
        assert destination.exists() != diagram
    print('Packaged alpha snapshots / empty diagram tiles / large pixel image allowed / diagram limit OK')

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    gui = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        try:
            code = gui.wait(timeout=3)
        except subprocess.TimeoutExpired:
            print("Packaged GUI: offscreen startup remained running (source GUI interaction checked separately)")
        else:
            raise AssertionError(f"Packaged GUI exited during startup: {code}")
    finally:
        gui.terminate()
        gui.wait(timeout=10)
print("Packaged release verification OK")
