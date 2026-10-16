"""用EXE内的实际模块运行UI检查，避免仅验证源码而漏掉打包版本。"""
import importlib.abc
import importlib.util
import runpy
import sys
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader

project = Path(__file__).resolve().parents[1]
exe = Path(sys.argv[1]).resolve()
script = sys.argv[2] if len(sys.argv) > 2 else 'version_ui'
archive = CArchiveReader(str(exe))
pyz = archive.open_embedded_archive('PYZ.pyz')
for path in (project / 'terraria_pixel').glob('*.py'):
    name = 'terraria_pixel' if path.stem == '__init__' else 'terraria_pixel.' + path.stem
    if name not in pyz.toc:
        continue  # 仅供研究/测试使用的模块不打入应用。
    packed = pyz.extract(name)
    expected = compile(path.read_bytes(), packed.co_filename, 'exec')
    assert packed == expected, name
print('Frozen application modules equal current source', flush=True)

class FrozenProject(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'terraria_pixel' or fullname.startswith('terraria_pixel.'):
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname == 'terraria_pixel')

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        code = pyz.extract(module.__name__)
        module.__file__ = code.co_filename
        if module.__name__ == 'terraria_pixel':
            module.__path__ = [str(project / 'terraria_pixel')]
        exec(code, module.__dict__)

sys.meta_path.insert(0, FrozenProject())
sys._MEIPASS = str(exe.parent / '_internal')
runpy.run_path(str(project / 'tests' / (script + '.py')), run_name='__main__')
