"""One local instance per Windows user; IPC activates or gracefully exits it."""
from __future__ import annotations
import ctypes
import os
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QLockFile, QStandardPaths, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard(QObject):
    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, name: str, parent: QObject | None = None, lock_dir: str | None = None):
        super().__init__(parent)
        self.name = name
        directory = Path(lock_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(directory / (name + ".lock")))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._read_connections)
        self._sockets = {}
        self.existing = not self.lock.tryLock(0)
        self.activated = False
        if self.existing:
            if self.lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("无法建立单实例锁，请检查本机设置目录是否可写。")
            self.activated = self.send_command(name, "SHOW")
        else:
            # Only the lock owner may remove a dead server endpoint.
            QLocalServer.removeServer(name)
            if not self.server.listen(name):
                self.lock.unlock()
                raise RuntimeError("无法建立 TimeTip 通信服务：" + self.server.errorString())

    @staticmethod
    def send_command(name: str, command: str, timeout_ms: int = 5000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(name)
            if not socket.waitForConnected(150):
                time.sleep(0.05)
                continue
            if not socket.bytesAvailable():
                socket.waitForReadyRead(500)
            greeting = bytes(socket.readAll()).decode("ascii", errors="ignore").strip()
            if command == "SHOW" and os.name == "nt" and greeting.startswith("PID "):
                try:
                    ctypes.windll.user32.AllowSetForegroundWindow(int(greeting[4:]))
                except (ValueError, OSError):
                    pass
            socket.write((command + "\n").encode("ascii"))
            if socket.bytesToWrite():
                socket.waitForBytesWritten(500)
            if not socket.bytesAvailable():
                socket.waitForReadyRead(1000)
            acknowledged = b"OK" in bytes(socket.readAll())
            socket.disconnectFromServer()
            return acknowledged
        return False

    def _read_connections(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._sockets[socket] = b""
            socket.readyRead.connect(lambda s=socket: self._consume(s))
            socket.disconnected.connect(lambda s=socket: self._discard(s))
            socket.write(f"PID {os.getpid()}\n".encode("ascii"))
            socket.flush()
            if socket.bytesAvailable():
                self._consume(socket)

    def _consume(self, socket):
        self._sockets[socket] = self._sockets.get(socket, b"") + bytes(socket.readAll())
        data = self._sockets[socket]
        if len(data) > 64:
            socket.abort()
            return
        if b"\n" not in data:
            return
        command = data.split(b"\n", 1)[0].strip()
        self._sockets[socket] = b""
        if command in (b"SHOW", b"QUIT"):
            socket.write(b"OK\n")
            socket.flush()
            signal = self.show_requested if command == b"SHOW" else self.quit_requested
            QTimer.singleShot(0, signal.emit)

    def _discard(self, socket):
        self._sockets.pop(socket, None)
        socket.deleteLater()

    def close(self):
        if not self.existing:
            self.server.close()
            self.lock.unlock()

