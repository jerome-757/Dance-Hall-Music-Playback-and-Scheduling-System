# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import glob

block_cipher = None

# Conda 环境路径
conda_library = r'C:\Users\riyyi\anaconda3\Library\bin'
conda_bin = r'C:\Users\riyyi\anaconda3\bin'

# 收集所有需要的 DLL
binaries = []

# 1. 从 Library/bin 收集
if os.path.exists(conda_library):
    for dll in glob.glob(os.path.join(conda_library, '*.dll')):
        dll_name = os.path.basename(dll).lower()
        # 包含 SDL 相关和关键 DLL
        if any(key in dll_name for key in ['sdl', 'libpng', 'zlib', 'libfreetype']):
            binaries.append((dll, '.'))
            print(f"Added from Library: {dll_name}")

# 2. 从 conda bin 收集
if os.path.exists(conda_bin):
    for dll in glob.glob(os.path.join(conda_bin, '*.dll')):
        dll_name = os.path.basename(dll).lower()
        if any(key in dll_name for key in ['python', 'vcruntime', 'msvcp']):
            binaries.append((dll, '.'))
            print(f"Added from bin: {dll_name}")

# 3. 确保 SDL2 系列全部包含
sdl_files = [
    'SDL2.dll',
    'SDL2_image.dll', 
    'SDL2_mixer.dll',
    'SDL2_ttf.dll',
]

for sdl_file in sdl_files:
    sdl_path = os.path.join(conda_library, sdl_file)
    if os.path.exists(sdl_path):
        # 确保不重复添加
        existing = [b[0] for b in binaries]
        if sdl_path not in existing:
            binaries.append((sdl_path, '.'))
            print(f"Added: {sdl_file}")

print(f"\nTotal binaries to include: {len(binaries)}")

a = Analysis(
    ['ballroom_player.py'],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        'pygame',
        'pygame.base',
        'pygame.sdl2',
        'pygame.image',
        'pygame.mixer',
        'pygame.font',
        'pygame.sprite',
        'pygame.locals',
        'os',
        'sys',
        'json',
        'time',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ballroom_player',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 改为 False 可以隐藏控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    cofile=None,
    icon=None,
)