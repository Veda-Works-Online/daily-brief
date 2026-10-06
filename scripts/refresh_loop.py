"""Bounded Actions worker; the workflow starts a successor after five hours."""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=60):
    return subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def next_tick(started, finished, interval):
    """Skip missed slots after a slow fetch; never overlap fetches."""
    return started + (int((finished - started) // interval) + 1) * interval


def git_revision(ref):
    return subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT,
                                   text=True, timeout=60).strip()


def cycle(branch):
    for attempt in range(3):
        # This is the disposable Actions checkout; only generated files are restored.
        run('git', 'restore', '--staged', '--worktree', '--', 'data')
        run('git', 'pull', '--ff-only', 'origin', branch)
        base = git_revision('HEAD')
        run(sys.executable, 'scripts/fetch_data.py', timeout=240)
        run('git', 'add', '--', 'data')
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
        if changed == 0:
            return
        if changed != 1:
            raise RuntimeError('Could not inspect generated data')
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        run('git', 'commit', '-m', 'data: refresh ' + stamp)
        try:
            run('git', 'push', 'origin', 'HEAD:' + branch)
            return
        except subprocess.CalledProcessError:
            run('git', 'fetch', 'origin', branch)
            remote = git_revision('FETCH_HEAD')
            advanced = subprocess.run(['git', 'merge-base', '--is-ancestor', base, remote],
                                      cwd=ROOT, timeout=60).returncode
            if remote == base or advanced != 0:
                # Authentication, network, branch protection or rewritten history:
                # do not disguise these failures as an ordinary concurrent edit.
                raise
            # Undo only our unpushed generated commit in this isolated checkout.
            # Regenerate from the latest branch, rather than rebase old market data.
            run('git', 'reset', '--soft', base)
            run('git', 'restore', '--staged', '--worktree', '--', 'data')
            print('::warning::Main advanced during refresh; discarded the unpushed '
                  'snapshot and will fetch fresh data.', flush=True)
    # Repeated edits must not stop the worker or create unbounded retries.
    # The next five-minute slot starts clean and pulls the latest branch again.
    print('::warning::Concurrent edits exhausted this cycle; retrying next slot.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration-seconds', type=int, default=18000)
    parser.add_argument('--interval-seconds', type=int, default=300)
    args = parser.parse_args()
    if args.duration_seconds < 1 or args.interval_seconds < 60:
        parser.error('duration must be positive and interval at least 60 seconds')
    branch = os.environ['DEFAULT_BRANCH']
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', 'github-actions[bot]@users.noreply.github.com')
    started = time.monotonic()
    deadline = started + args.duration_seconds
    while time.monotonic() < deadline:
        try:
            cycle(branch)
        except (subprocess.SubprocessError, RuntimeError) as exc:
            # A successor uses a clean checkout and reruns checks. Do not
            # continue from a rejected commit or a partly generated snapshot.
            evidence = ROOT / 'work' / 'refresh-failure.json'
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text(json.dumps({'status': 'FAILED',
                'failed_at': datetime.now(timezone.utc).isoformat(),
                'reason': type(exc).__name__}), encoding='utf-8')
            print('::error::Refresh interrupted: ' + type(exc).__name__, flush=True)
            return 1
        tick = next_tick(started, time.monotonic(), args.interval_seconds)
        time.sleep(max(0, min(tick, deadline) - time.monotonic()))


if __name__ == '__main__':
    sys.exit(main())
