"""Single source of truth for the package version.

Reads the installed distribution's version so ``getterdone.__version__`` can
never drift from what pip installed (DevX cell-5 finding: ``__version__``
reported 1.1.0 on a v1.1.6 install because the release pipeline bumps only
``pyproject.toml``). The literal fallback is used only for source checkouts
that were never pip-installed.
"""

try:
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("getterdone")
except Exception:  # pragma: no cover — source checkout / not installed
    __version__ = "1.2.0"
