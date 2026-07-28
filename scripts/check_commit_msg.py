"""Menegakkan Conventional Commits pada pesan commit.

Dipanggil oleh pre-commit pada stage `commit-msg`. Sengaja tanpa dependensi
eksternal supaya berlaku untuk siapa pun yang meng-clone repo ini.

Format:  <type>(<scope>)!: <subject>
Contoh:  feat(tools): add profile_column
         fix(execution)!: include tool_version in fingerprint
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = (
    "feat",
    "fix",
    "docs",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)

PATTERN = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([a-z0-9._\-/]+\))?!?: .{{1,72}}$")

MAX_SUBJECT = 72


def main() -> int:
    if len(sys.argv) < 2:
        print("check_commit_msg.py: butuh path file pesan commit")
        return 1

    # utf-8-sig: sebagian editor menulis BOM di awal file pesan commit.
    # Git sendiri tidak, tapi kegagalan karena BOM sangat membingungkan untuk didiagnosis.
    lines = Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines()
    subject = next((ln for ln in lines if ln.strip() and not ln.startswith("#")), "")

    # Commit otomatis dari git (merge/revert/fixup) dilewati.
    if subject.startswith(("Merge ", "Revert ", "fixup!", "squash!")):
        return 0

    if PATTERN.match(subject):
        return 0

    print("\nPesan commit tidak mengikuti Conventional Commits.\n")
    print(f"  Ditulis : {subject!r}")
    print(f"  Format  : <type>(<scope>)!: <subject>   (maks {MAX_SUBJECT} karakter)")
    print(f"  Type     : {', '.join(TYPES)}")
    print("\n  Contoh  : feat(tools): add profile_column")
    print("            fix(execution)!: include tool_version in fingerprint\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
