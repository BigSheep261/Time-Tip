import json
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from app.infrastructure.single_instance import SingleInstanceGuard


class SingleInstanceTests(unittest.TestCase):
    def read_when_ready(self, path):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                return json.loads(path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
        self.fail('Timed out waiting for IPC fixture: ' + str(path))

    def test_concurrent_launch_wakes_hidden_owner_and_crash_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            channel = 'TimeTip.Test.' + uuid.uuid4().hex
            args = [sys.executable, str(Path(__file__).with_name('instance_probe.py')), directory, channel]
            children = []
            try:
                for name in ('a', 'b'):
                    children.append(subprocess.Popen(args + [name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                results = [self.read_when_ready(folder / (name + '.json')) for name in ('a', 'b')]
                self.assertEqual(sorted(r['role'] for r in results), ['primary', 'secondary'])
                primary_index = next(i for i, r in enumerate(results) if r['role'] == 'primary')
                owner = children[primary_index]
                second = children[1 - primary_index]
                second.wait(timeout=5)
                self.assertEqual(second.returncode, 0)
                active = self.read_when_ready(folder / 'activation.json')
                self.assertEqual(active['pid'], owner.pid)
                self.assertTrue(active['visible'])
                self.assertFalse(active['minimized'])
                self.assertIsNone(owner.poll())
                # Forced death leaves lock/socket artifacts, which the next owner must recover.
                owner.kill()
                owner.wait(timeout=5)
                successor = subprocess.Popen(args + ['c'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                children.append(successor)
                self.assertEqual(self.read_when_ready(folder / 'c.json')['role'], 'primary')
                self.assertTrue(SingleInstanceGuard.send_command(channel, 'QUIT'))
                successor.wait(timeout=5)
                self.assertEqual(successor.returncode, 0)
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
