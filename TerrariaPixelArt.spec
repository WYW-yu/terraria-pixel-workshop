# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[SPECPATH],
    binaries=[],
    datas=[('icon.ico', '.'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=['tools/pyinstaller_hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtNetwork', 'PIL.AvifImagePlugin', 'PIL._avif',
              'PIL.Jpeg2KImagePlugin', 'PIL.ImageTk', 'tkinter'],
    noarchive=False,
    optimize=0,
)
# QWidget/QPainter use Qt's raster renderer. Keep the Windows/offscreen
# platform plugins, supported image formats and our own Chinese translation.
# Networking, TLS and the software OpenGL renderer are not used by this app.
def required_runtime(entry):
    name = entry[0].replace('\\', '/').lower()
    if name.startswith('pyside6/translations/'):
        return False
    if any(name.startswith('pyside6/plugins/' + group + '/')
           for group in ('generic', 'networkinformation', 'tls')):
        return False
    if name.startswith('pyside6/') and name.rsplit('/', 1)[-1] in (
            'opengl32sw.dll', 'qt6network.dll', 'qtnetwork.pyd'):
        return False
    return True

a.binaries = [entry for entry in a.binaries if required_runtime(entry)]
a.datas = [entry for entry in a.datas if required_runtime(entry)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TerrariaPixelArt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TerrariaPixelArt',
)
