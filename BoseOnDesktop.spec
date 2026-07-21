# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_all

hiddenimports = ['pystray._win32', 'hid']
hiddenimports += collect_submodules('pybmap')

# Static web UI served by the pywebview window (window.py resolves it under
# _MEIPASS/bosewin/webui).
datas = [('bosewin\\webui', 'bosewin\\webui')]

# pywebview + its EdgeChromium (WebView2) backend and the pythonnet bridge it
# loads at runtime. collect_all pulls webview's bundled WebView2 loader DLLs.
_wv_datas, _wv_bins, _wv_hidden = collect_all('webview')
datas += _wv_datas
hiddenimports += _wv_hidden
hiddenimports += ['clr_loader', 'clr_loader.ffi']
for _pkg in ('clr_loader', 'pythonnet'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        _wv_bins += _b
        hiddenimports += _h
    except Exception:
        pass


a = Analysis(
    ['boseondesktop_tray.py'],
    pathex=['ref-bosectl\\python'],
    binaries=_wv_bins,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BoseOnDesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='bosewin\\app.ico',
)
