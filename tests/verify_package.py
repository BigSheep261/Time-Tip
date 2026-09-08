"""Windows packaged integration checks in a disposable workspace directory.

No desktop shortcuts, real registry settings or installed user processes are modified.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QCoreApplication
from app.infrastructure.single_instance import SingleInstanceGuard
from app.infrastructure.store import Store


def verify():
    root = Path(__file__).resolve().parents[1]
    package = root / 'TimeTip-Setup.exe'
    csc = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    qt_app = QCoreApplication.instance() or QCoreApplication([])
    with tempfile.TemporaryDirectory(prefix='package-check-', dir=root / 'build') as directory:
        work = Path(directory)
        assert work.resolve().is_relative_to((root / 'build').resolve())
        harness = work / 'harness.exe'
        subprocess.run([str(csc), '/nologo', '/target:exe', '/main:InstallerHarness',
                        '/reference:System.Windows.Forms.dll', '/reference:System.IO.Compression.dll',
                        '/reference:System.IO.Compression.FileSystem.dll', '/codepage:65001',
                        '/out:' + str(harness), str(root / 'installer_stub.cs'), str(root / 'tests/installer_harness.cs')], check=True)
        installed = work / 'Installed App'
        profile = str(work / 'profile' / 'settings.ini')
        Path(profile).parent.mkdir()
        channel = 'TimeTip.SingleInstance.Test.' + hashlib.sha256(profile.lower().encode()).hexdigest()[:16]
        env = {**os.environ, 'TIMETIP_TEST_PROFILE': profile, 'QT_QPA_PLATFORM': 'offscreen'}
        def install(source=package, expected=0):
            result = subprocess.run([str(harness), str(source), str(installed), channel], capture_output=True, timeout=40)
            assert result.returncode == expected, result.stderr.decode(errors='replace')
        def ready():
            assert SingleInstanceGuard.send_command(channel, 'SHOW', timeout_ms=8000), 'Packaged app did not answer IPC'
        def stop(process):
            if process.poll() is None:
                SingleInstanceGuard.send_command(channel, 'QUIT', timeout_ms=1000)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        install()
        exe = installed / 'TimeTip.exe'
        digest = hashlib.sha256(exe.read_bytes()).hexdigest()
        assert digest == hashlib.sha256((root / 'dist/TimeTip/TimeTip.exe').read_bytes()).hexdigest()
        (installed / 'keep-user-file.txt').write_text('keep')
        (installed / '_internal' / 'obsolete.dll').write_text('old')
        settings = Store(profile)
        settings.write_json('memos', [dict(id='keep', title='Saved note', text='Preserve across upgrade')])
        primary = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            ready()
            secondary = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                secondary.wait(timeout=10)
                assert secondary.returncode == 0
            finally:
                stop(secondary)
            assert primary.poll() is None
            quoted = str(exe).replace("'", "''")
            powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            count = subprocess.check_output([powershell, '-NoProfile', '-Command',
                "@(Get-Process TimeTip -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq '" + quoted + "' }).Count"], text=True)
            assert count.strip() == '1', 'Expected exactly one installed TimeTip process: ' + count
            corrupt = work / 'corrupted.exe'
            shutil.copyfile(package, corrupt)
            with corrupt.open('r+b') as stream:
                stream.seek(-49, 2)
                byte = stream.read(1)
                stream.seek(-1, 1)
                stream.write(bytes([byte[0] ^ 1]))
            install(corrupt, expected=2)
            assert primary.poll() is None, 'A bad package stopped the running app'
            assert hashlib.sha256(exe.read_bytes()).hexdigest() == digest
            install()
            primary.wait(timeout=5)
            assert primary.returncode == 0, 'Upgrade did not gracefully quit the old app'
            assert (installed / 'keep-user-file.txt').read_text() == 'keep'
            assert not (installed / '_internal' / 'obsolete.dll').exists()
            assert Store(profile).read_json('memos', [])[0]['text'] == 'Preserve across upgrade'
            assert Store(profile).get('window_geometry'), 'Graceful exit did not save geometry'
            assert not list(installed.glob('.update-*'))
            again = subprocess.Popen([str(exe)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                ready()
            finally:
                stop(again)
            assert again.returncode == 0
        finally:
            stop(primary)
        # Inject a runtime-file replacement failure after the executable has already been replaced.
        exe.write_bytes(b'old-version-fixture')
        rollback = subprocess.run([str(harness), 'rollback', str(package), str(installed), channel], capture_output=True, timeout=40)
        assert rollback.returncode == 2
        assert exe.read_bytes() == b'old-version-fixture', 'Failed replacement did not restore the old executable'
        assert not list(installed.glob('.update-*'))
        install()
        assert hashlib.sha256(exe.read_bytes()).hexdigest() == digest
        malicious = work / 'bad.zip'
        with zipfile.ZipFile(malicious, 'w') as zip_file:
            zip_file.writestr('../outside.txt', 'not allowed')
        destination = work / 'extract'
        destination.mkdir()
        rejected = subprocess.run([str(harness), 'extract', str(malicious), str(destination)], capture_output=True)
        assert rejected.returncode == 2
        assert not (work / 'outside.txt').exists()
    print('Package checks passed: fresh install, one process, repeat launch, corrupt-package preservation, live upgrade, settings preservation, relaunch, rollback, archive path validation.')


if __name__ == '__main__':
    verify()
