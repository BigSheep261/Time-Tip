from pathlib import Path

import PyQt6
from PyInstaller.utils.hooks import collect_submodules


project = Path(SPECPATH).parent
assets = project / "assets"
analysis = Analysis(
    [str(project / "timetip.py")],
    pathex=[str(project)],
    datas=[(str(assets / name), "assets") for name in ("timetip.png", "anime-default-cover.png")],
    hiddenimports=collect_submodules("app.features") + collect_submodules("jmcomic") + ["fitz", "pyzipper"],
    noarchive=False,
)

# Use the Qt wheel's VC runtime and let Windows provide UCRT and its API sets.
qt_bin = Path(PyQt6.__file__).parent / "Qt6" / "bin"
binaries = []
for destination, source, kind in analysis.binaries:
    name = Path(destination).name.lower()
    if name == "ucrtbase.dll" or name.startswith("api-ms-win-"):
        continue
    if name in ("vcruntime140.dll", "vcruntime140_1.dll") and (qt_bin / name).is_file():
        source = str(qt_bin / name)
    binaries.append((destination, source, kind))

pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="TimeTip",
    console=False, upx=False, icon=str(assets / "timetip.ico"),
)
dist = COLLECT(exe, binaries, analysis.datas, name="TimeTip", upx=False)
