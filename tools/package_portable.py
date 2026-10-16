"""仅打包主EXE、运行库和说明；不包含用户历史、作品或开发文件。"""
from pathlib import Path
from shutil import copy2
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'dist-v5.2'
APP = RELEASE / 'TerrariaPixelArt'
ALLOWED = {'TerrariaPixelArt.exe', '_internal', '使用说明.txt'}

def main():
    # 源码中的说明与用户确认稿一致；每次打包同步，避免发行目录残留旧稿。
    manual = ROOT / '使用说明.txt'
    if not manual.is_file():
        raise FileNotFoundError('缺少用户确认的使用说明.txt')
    if not APP.is_dir():
        raise FileNotFoundError(f'缺少发行程序目录：{APP}')
    copy2(manual, APP / manual.name)
    for name in ALLOWED:
        if not (APP / name).exists():
            raise FileNotFoundError(f'缺少必需的发行文件：{name}')
    files = sorted(p for p in APP.rglob('*')
                   if p.is_file() and p.relative_to(APP).parts[0] in ALLOWED
                   and p.name.upper() not in {'INSTALLER', 'INSTALLER.TXT'})
    archive = RELEASE / '泰拉瑞拉像素工坊-v5.2.zip'
    with ZipFile(archive, 'w', ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, p.relative_to(RELEASE))
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('发行压缩包完整性检查失败')
        assert {name.split('/')[1] for name in z.namelist()} == ALLOWED
    print(archive, 'files:', len(files))

if __name__ == '__main__':
    main()
