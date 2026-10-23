"""RedQueen package initialiser."""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("redqueen")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
