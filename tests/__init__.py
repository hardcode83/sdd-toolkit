"""Test package.

Every test repository is a throwaway git repo, and `git push`/`git fetch` on
one may leave a detached `git gc --auto` writing `.git/objects` while the
TemporaryDirectory is being removed — CI failed once on exactly that race
(`OSError: Directory not empty: 'objects'`). Disable automatic gc for every git
process the tests spawn, including the ones the toolkit's scripts spawn.
"""

from __future__ import annotations

import os

os.environ.setdefault("GIT_CONFIG_COUNT", "2")
os.environ.setdefault("GIT_CONFIG_KEY_0", "gc.auto")
os.environ.setdefault("GIT_CONFIG_VALUE_0", "0")
os.environ.setdefault("GIT_CONFIG_KEY_1", "gc.autoDetach")
os.environ.setdefault("GIT_CONFIG_VALUE_1", "false")
