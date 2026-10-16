"""打包当前完整源码，排除用户作品、发行二进制与构建缓存。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
ROOT = Path(__file__).resolve().parents[1]
names = ['main.py', 'run.py', 'run.bat', 'requirements.txt', 'README.md', 'icon.ico', 'version_info.txt', 'TerrariaPixelArt.spec',
         '打包.bat', '使用说明.txt', '算法说明.md', '游戏颜色校准说明.md',
         '源码阅读说明.md', '开发交接说明.md', '代码审查复核.md', '世界导入验证.md', 'v4.13验证记录.md', 'v5.1验证记录.md', 'v5.2验证记录.md']
files = [ROOT / name for name in names]
for folder in ['terraria_pixel', 'tests', 'tools', 'assets']:
    files += [p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts
              and p.suffix in {'.py', '.js', '.json', '.jpg', '.qm', '.tr', '.z'}]
archive = ROOT / '泰拉瑞拉像素工坊-v5.2-源码.zip'
with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as z:
    for p in sorted(files):
        z.write(p, Path('terraria-pixel-art') / p.relative_to(ROOT))
with ZipFile(archive) as z:
    assert z.testzip() is None
    for p in files:
        assert z.read('terraria-pixel-art/' + p.relative_to(ROOT).as_posix()) == p.read_bytes()
print(archive, 'files:', len(files))
