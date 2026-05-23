# build.spec — PyInstaller spec for CAS Manager (macOS .app bundle).
#
# Build:
#     pip install pyinstaller pywebview platformdirs
#     pyinstaller build.spec
# Result:
#     dist/CAS Manager.app
#
# Notes:
# - `cas` and `mb_login` are pulled in via importlib.import_module() at
#   runtime in cas_controller.ctrl_*, so PyInstaller can't see them
#   statically — they go into `hiddenimports`.
# - `cas.py` does `import anthropic` lazily inside _ai_via_anthropic() so
#   it's only required if the user picks the Anthropic provider. We list it
#   as a hidden import so it's bundled when present, but the build won't
#   fail if anthropic isn't installed (PyInstaller warns and skips).
# - `tkinter` etc. are excluded — we don't use them, and they bloat the
#   bundle by ~30 MB.

block_cipher = None


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static',    'static'),
    ],
    hiddenimports=[
        'cas',
        'cas_api',
        'cas_db',
        'cas_controller',
        'cas_errors',
        'cas_prompts',
        'cas_paths',
        'cas_web',
        'mb_login',
        'anthropic',    # optional; only used if ai_provider="anthropic"
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'IPython', 'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CAS Manager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,     # match host arch (arm64 on Apple Silicon)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CAS Manager',
)

app = BUNDLE(
    coll,
    name='CAS Manager.app',
    icon=None,            # add 'icon.icns' once we have one
    bundle_identifier='com.casmanager.app',
    info_plist={
        'NSHighResolutionCapable':       'True',
        'LSBackgroundOnly':              'False',
        'CFBundleShortVersionString':    '0.1.0',
        'CFBundleVersion':               '0.1.0',
        'NSPrincipalClass':              'NSApplication',
        # Allow the embedded webview to talk to localhost over HTTP
        'NSAppTransportSecurity': {
            'NSAllowsLocalNetworking': True,
        },
    },
)
