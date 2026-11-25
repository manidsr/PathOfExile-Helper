a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.')],
    hiddenimports=[
        # pystray's Windows backend and Pillow's tk glue aren't always
        # picked up automatically since they're imported lazily/dynamically
        # (see gui.py's tray-icon code and PIL's ImageTk).
        'pystray',
        'pystray._win32',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries go into COLLECT below, not into the exe
    name='PathOfExileHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # main.pyw has no console window - keep this False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PathOfExileHelper',      # -> dist\PathOfExileHelper\  (folder, not a single file)
)
