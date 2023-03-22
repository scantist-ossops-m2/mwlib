import importlib.metadata
from pathlib import Path

import toml

root_dir = Path(__file__).resolve().parent.parent.parent


def get_version_from_pyproject():
    with open(root_dir / "pyproject.toml", encoding="utf-8") as file:
        pyproject_data = toml.load(file)
        v = pyproject_data["project"]["version"]
        return v


def get_version_from_package(package_name):
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


version = get_version_from_pyproject()
__version_info__ = tuple(map(int, version.split(".")))
display_version = __version__ = version


def main():
    for r in ("mwlib", "mwlib.rl", "mwlib.ext", "mwlib.hiq"):
        v = get_version_from_package(r)
        if v:
            print(r, v)


if __name__ == "__main__":
    main()
