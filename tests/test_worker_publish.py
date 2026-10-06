"""Exercise publication races against a local bare Git remote; no providers/network."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import refresh_loop as worker


class PublishRaceTests(unittest.TestCase):
    def git(self, cwd, *args):
        return subprocess.check_output(['git', *args], cwd=cwd, text=True,
                                       stderr=subprocess.PIPE).strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote, self.checkout, self.editor = [root / n for n in ('remote.git', 'worker', 'editor')]
        self.git(root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        self.git(root, 'clone', str(self.remote), str(self.checkout))
        self.git(self.checkout, 'config', 'user.name', 'Test worker')
        self.git(self.checkout, 'config', 'user.email', 'worker@example.invalid')
        (self.checkout / 'data').mkdir()
        (self.checkout / 'scripts').mkdir()
        (self.checkout / 'listings.txt').write_text('original')
        (self.checkout / 'data/stocks.json').write_text('{}')
        (self.checkout / 'scripts/fetch_data.py').write_text(
            'import json\nfrom pathlib import Path\n'
            'root = Path(__file__).resolve().parents[1]\n'
            'path = root / "data/stocks.json"\n'
            'old = json.loads(path.read_text())\n'
            'path.write_text(json.dumps({"listings": (root / "listings.txt").read_text(), '
            '"generation": old.get("generation", 0) + 1}))\n')
        self.git(self.checkout, 'add', '.')
        self.git(self.checkout, 'commit', '-m', 'initial')
        self.git(self.checkout, 'push', 'origin', 'main')
        self.git(root, 'clone', str(self.remote), str(self.editor))
        self.git(self.editor, 'config', 'user.name', 'Test editor')
        self.git(self.editor, 'config', 'user.email', 'editor@example.invalid')
        self.commands = []
        self.real_run = worker.run

    def edit_remote(self):
        self.git(self.editor, 'pull', '--ff-only', 'origin', 'main')
        path = self.editor / 'listings.txt'
        path.write_text(path.read_text() + ' + new listing')
        self.git(self.editor, 'add', 'listings.txt')
        self.git(self.editor, 'commit', '-m', 'user adds listing')
        self.git(self.editor, 'push', 'origin', 'main')

    def run_with_races(self, races):
        remaining = races
        def command(*args, **kwargs):
            nonlocal remaining
            self.commands.append(args)
            if args[:2] == ('git', 'push') and remaining:
                remaining -= 1
                self.edit_remote()
            return self.real_run(*args, **kwargs)
        with patch.object(worker, 'ROOT', self.checkout), patch.object(worker, 'run', side_effect=command):
            worker.cycle('main')

    def test_concurrent_edit_regenerates_data_and_preserves_user_commit(self):
        self.run_with_races(1)
        snapshot = json.loads(self.git(self.remote, 'show', 'main:data/stocks.json'))
        self.assertEqual(snapshot['listings'], 'original + new listing')
        self.assertEqual(snapshot['generation'], 1)
        self.assertEqual(self.git(self.remote, 'show', 'main:listings.txt'), snapshot['listings'])
        self.assertIn('user adds listing', self.git(self.remote, 'log', '--format=%s', 'main'))
        self.assertEqual(len([c for c in self.commands if c[0] == sys.executable]), 2)
        self.assertFalse(any('--force' in c or '--force-with-lease' in c for c in self.commands))

    def test_repeated_edits_skip_cleanly_and_next_slot_recovers(self):
        self.run_with_races(3)
        self.assertEqual(self.git(self.remote, 'show', 'main:data/stocks.json'), '{}')
        self.assertEqual(self.git(self.checkout, 'status', '--porcelain'), '')
        self.run_with_races(0)
        snapshot = json.loads(self.git(self.remote, 'show', 'main:data/stocks.json'))
        self.assertEqual(snapshot['listings'].count('new listing'), 3)

    def test_push_failure_without_remote_advance_is_not_hidden(self):
        def command(*args, **kwargs):
            self.commands.append(args)
            if args[:2] == ('git', 'push'):
                raise subprocess.CalledProcessError(1, args)
            return self.real_run(*args, **kwargs)
        with patch.object(worker, 'ROOT', self.checkout), patch.object(worker, 'run', side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError):
                worker.cycle('main')
        self.assertFalse(any(c[:2] == ('git', 'reset') for c in self.commands))
        self.assertEqual(self.git(self.remote, 'show', 'main:data/stocks.json'), '{}')


if __name__ == '__main__':
    unittest.main()
