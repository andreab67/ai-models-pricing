"""Model pricing optimizer backend."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("model-pricing-api")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "1.4.0"
