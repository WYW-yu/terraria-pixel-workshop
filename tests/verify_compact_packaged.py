"""实际精简EXE的全部受支持图片格式及无落盘展开验证。"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
from terraria_pixel.pipeline import prepare_preview
from terraria_pixel.history import load_record

exe = Path(sys.argv[1]).resolve()
assets = exe.parent / '_internal/assets'
before = {p.name: p.stat().st_size for p in assets.iterdir() if p.is_file()}
with tempfile.TemporaryDirectory(prefix='compact-codecs-', dir=project.parent / '.tmp') as directory:
    root = Path(directory)
    rgb = np.random.default_rng(5016).integers(0, 256, (8, 12, 3), np.uint8)
    for suffix, fmt in [('png', 'PNG'), ('jpg', 'JPEG'), ('jpeg', 'JPEG'), ('bmp', 'BMP'),
                        ('gif', 'GIF'), ('webp', 'WEBP'), ('tif', 'TIFF'), ('tiff', 'TIFF')]:
        source = root / ('输入.' + suffix)
        Image.fromarray(rgb).save(source, format=fmt)
        destination = root / suffix
        run = subprocess.run([str(exe), str(source), '--width', '12', '--sampling', 'nearest', '--out', str(destination)],
                             timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert run.returncode == 0, suffix
        result = load_record(next(destination.iterdir()))
        expected = prepare_preview(source, width=12, sampling='nearest')
        for name in ('processed_rgb', 'grid', 'grid_wall', 'grid_map'):
            np.testing.assert_array_equal(getattr(result, name), getattr(expected, name))
        print('Frozen codec / all material modes:', suffix, flush=True)
assert before == {p.name: p.stat().st_size for p in assets.iterdir() if p.is_file()}
assert not any(p.stat().st_size > 1_000_000 for p in assets.glob('*.tr'))
print('Compressed map data stayed compressed on disk; image formats verified')
