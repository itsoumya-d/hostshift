"""Enable `python -m hostshift` as an alias for `python -m hostshift.runner`."""

import sys

from .runner import main

if __name__ == "__main__":
    sys.exit(main())
