"""Check release sources and built metadata without third-party dependencies."""

import argparse
import re
import sys
import tarfile
import tomllib
import zipfile
from datetime import date
from email.parser import BytesParser
from pathlib import Path

VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


def check_sources(root: Path, tag: str | None = None) -> tuple[str, str]:
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    name, version = project["name"], project["version"]
    if not re.fullmatch(VERSION, version):
        raise ValueError(f"Expected a stable MAJOR.MINOR.PATCH version, got {version!r}")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Release tag {tag!r} does not match package version v{version}")

    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    local = [p for p in packages if p.get("source", {}).get("editable") == "."]
    if len(local) != 1 or (local[0]["name"], local[0]["version"]) != (name, version):
        raise ValueError(
            "uv.lock local package name/version must match pyproject.toml; run uv lock"
        )

    changelog = (root / "CHANGELOG.md").read_text()
    sections = list(re.finditer(r"^## \[([^\]]+)\](.*)$", changelog, re.MULTILINE))
    releases = [s for s in sections if s[1] != "Unreleased"]
    if not releases or releases[0][1] != version:
        raise ValueError(f"Newest released CHANGELOG.md section must be [{version}]")
    if sum(s[1] == version for s in releases) != 1:
        raise ValueError(f"CHANGELOG.md contains duplicate [{version}] sections")
    latest = releases[0]
    stamp = re.fullmatch(r" - (\d{4}-\d{2}-\d{2})\s*", latest[2])
    if stamp is None:
        raise ValueError(f"CHANGELOG.md [{version}] needs a YYYY-MM-DD release date")
    date.fromisoformat(stamp[1])
    end = next((s.start() for s in sections if s.start() > latest.start()), len(changelog))
    if not re.search(r"^- \S", changelog[latest.end() : end], re.MULTILINE):
        raise ValueError(f"CHANGELOG.md [{version}] needs release notes")
    return name, version


def _check_metadata(data: bytes, name: str, version: str, artifact: Path) -> None:
    metadata = BytesParser().parsebytes(data)
    if metadata.get_all("Name") != [name] or metadata.get_all("Version") != [version]:
        raise ValueError(f"{artifact.name}: embedded Name/Version must be {name} {version}")


def check_artifacts(dist: Path, name: str, version: str) -> None:
    # uv build creates this bookkeeping file; it is not a publishable artifact.
    files = [p for p in dist.iterdir() if p.name != ".gitignore"]
    wheels = [p for p in files if p.suffix == ".whl"]
    sdists = [p for p in files if p.name.endswith(".tar.gz")]
    if len(files) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Distribution directory must contain exactly one wheel and one sdist")

    normalized_name = re.sub(r"[-_.]+", "_", name)
    stem = f"{normalized_name}-{version}"
    wheel = wheels[0]
    if not re.fullmatch(rf"{re.escape(stem)}-[^-]+-[^-]+-[^-]+\.whl", wheel.name):
        raise ValueError(f"Unexpected wheel filename: {wheel.name}; expected {stem}-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        members = [p for p in archive.namelist() if p.endswith(".dist-info/METADATA")]
        if members != [f"{stem}.dist-info/METADATA"]:
            raise ValueError(f"{wheel.name}: expected exactly one matching METADATA entry")
        _check_metadata(archive.read(members[0]), name, version, wheel)

    sdist = sdists[0]
    if sdist.name != f"{stem}.tar.gz":
        raise ValueError(f"Unexpected sdist filename: {sdist.name}; expected {stem}.tar.gz")
    with tarfile.open(sdist, "r:gz") as archive:
        tar_members = [p for p in archive.getmembers() if p.name == f"{stem}/PKG-INFO"]
        if len(tar_members) != 1 or not tar_members[0].isfile():
            raise ValueError(f"{sdist.name}: expected exactly one root PKG-INFO file")
        stream = archive.extractfile(tar_members[0])
        assert stream is not None
        with stream:
            _check_metadata(stream.read(), name, version, sdist)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", help="Exact release tag, e.g. v1.4.1")
    parser.add_argument("--dist", type=Path, help="Also validate wheel and sdist metadata")
    args = parser.parse_args()
    try:
        name, version = check_sources(args.root, args.tag)
        if args.dist is not None:
            check_artifacts(args.dist, name, version)
    except (ValueError, OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release consistency check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release consistency checks passed: {name} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
