"""HostShift: measuring cross-platform portability of LLM-generated UIs.

    from hostshift import runner
    from hostshift.render import open_session

The command line is the primary interface:

    hostshift --version
    hostshift plan | lint | demo | report | calibrate | coverage
"""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["__version__"]
