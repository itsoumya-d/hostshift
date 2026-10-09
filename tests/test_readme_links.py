"""Relative README entry links must resolve in the public checkout."""

import pathlib
import re
import sys
from urllib.parse import unquote, urlsplit


def test_readme_relative_link_targets_exist():
    root = pathlib.Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    missing = []
    for target in re.findall(r"\]\(([^\s)]+)", readme):
        parsed = urlsplit(target.strip("<>"))
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        relative = unquote(parsed.path)
        if not (root / relative).exists():
            missing.append(relative)
    assert not missing, f"README links to absent checkout paths: {missing}"


if __name__ == "__main__":
    try:
        test_readme_relative_link_targets_exist()
    except Exception as error:
        print(f"  FAIL test_readme_relative_link_targets_exist: {error}")
        print("0/1 passed")
        sys.exit(1)
    print("  PASS test_readme_relative_link_targets_exist")
    print("1/1 passed")
