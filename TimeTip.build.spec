import os
from pathlib import Path
import PyQt6

project = Path(SPECPATH)
qt_bin = Path(PyQt6.__file__).parent / 'Qt6' / 'bin'
debug = os.environ.get('TIMETIP_DEBUG_BUILD') == '1'
a = Analysis([str(project / 'timetip.py')], pathex=[str(project)], binaries=[], datas=[], hiddenimports=[], hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
# Windows 10/11 supply UCRT and API sets. Older copies from unrelated tools
# can shadow the OS runtime and prevent Qt from loading in the frozen app.
clean_binaries = []
for destination, source, kind in a.binaries:
    name = Path(destination).name.lower()
    if name in ('ucrtbase.dll', 'icuuc.dll', 'icuin.dll') or name.startswith(('api-ms-win-', 'icudt')):
        continue
    if name in ('vcruntime140.dll', 'vcruntime140_1.dll') and (qt_bin / name).exists():
        source = str(qt_bin / name)
    clean_binaries.append((destination, source, kind))
a.binaries = clean_binaries
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TimeTip-debug' if debug else 'TimeTip', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=debug, icon=str(project / 'assets' / 'timetip.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TimeTip-debug' if debug else 'TimeTip')
