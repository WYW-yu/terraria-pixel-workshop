"""打包当前源码，排除用户数据、发行文件、缓存与生成报告。"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    '.gitattributes', '.gitignore', 'main.py', 'run.py', 'run.bat',
    'requirements.txt', 'README.md', 'icon.ico', 'version_info.txt',
    'TerrariaPixelArt.spec', '打包.bat', '使用说明.txt', '算法说明.md',
)
SOURCE_FOLDERS = ('terraria_pixel', 'tools', 'assets', 'tests')
SOURCE_SUFFIXES = {'.py', '.js', '.json', '.jpg', '.qm', '.tr', '.z', '.md'}


def main():
    files = [ROOT / name for name in ROOT_FILES]
    for folder in SOURCE_FOLDERS:
        files.extend(p for p in (ROOT / folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix in SOURCE_SUFFIXES
                     and not p.name.endswith('_calibration.json')
                     and p.name != 'map_compression.json')
    archive = ROOT / '泰拉瑞拉像素工坊-v5.2-源码.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(files):
            z.write(p, Path('terraria-pixel-art') / p.relative_to(ROOT))
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('源码压缩包完整性检查失败')
        for p in files:
            if z.read('terraria-pixel-art/' + p.relative_to(ROOT).as_posix()) != p.read_bytes():
                raise ValueError(f'源码压缩包内容不一致：{p.name}')
    print(archive, 'files:', len(files))


if __name__ == '__main__':
    main()
