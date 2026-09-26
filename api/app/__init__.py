"""Model pricing optimizer backend."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version() -> str:
    try:
        return version("model-pricing-api")
    except PackageNotFoundError:
        # The container installs dependencies only and runs from source, so
        # read the version from the pyproject.toml shipped next to the app.
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        try:
            with pyproject.open("rb") as f:
                return str(tomllib.load(f)["project"]["version"])
        except (OSError, KeyError, tomllib.TOMLDecodeError):
            return "0.0.0+unknown"


__version__ = _version()
