"""Release checks reject stale sources and mislabeled distribution metadata."""

import io
import runpy
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release.py"
checks = runpy.run_path(str(SCRIPT))
check_sources = checks["check_sources"]
check_artifacts = checks["check_artifacts"]


@pytest.fixture
def release_root(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "redress"\nversion = "1.4.1"\n')
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "redress"\nversion = "1.4.1"\nsource = {editable = "."}\n'
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.4.1] - 2026-09-24\n\n### Fixed\n- Retry bug.\n"
    )
    return tmp_path


def make_artifacts(dist, *, wheel_version="1.4.1", sdist_version="1.4.1", name="redress"):
    dist.mkdir(exist_ok=True)
    with zipfile.ZipFile(dist / "redress-1.4.1-py3-none-any.whl", "w") as archive:
        archive.writestr(
            "redress-1.4.1.dist-info/METADATA", f"Name: {name}\nVersion: {wheel_version}\n"
        )
    data = f"Name: {name}\nVersion: {sdist_version}\n".encode()
    with tarfile.open(dist / "redress-1.4.1.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo("redress-1.4.1/PKG-INFO")
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))


def test_valid_release_sources_and_artifacts(release_root):
    assert check_sources(release_root, "v1.4.1") == ("redress", "1.4.1")
    make_artifacts(release_root / "dist")
    check_artifacts(release_root / "dist", "redress", "1.4.1")


@pytest.mark.parametrize("tag", ["v1.4.0", "v1.4.2", "1.4.1", "main", ""])
def test_reject_wrong_release_tag(release_root, tag):
    with pytest.raises(ValueError, match="tag"):
        check_sources(release_root, tag)


def test_reject_original_release_mismatch(release_root):
    for filename in ("pyproject.toml", "uv.lock"):
        p = release_root / filename
        p.write_text(p.read_text().replace("1.4.1", "1.4.0"))
    with pytest.raises(ValueError, match="tag"):
        check_sources(release_root, "v1.4.1")
    with pytest.raises(ValueError, match="Newest released"):
        check_sources(release_root)


def test_reject_stale_lockfile(release_root):
    p = release_root / "uv.lock"
    p.write_text(p.read_text().replace("1.4.1", "1.4.0"))
    with pytest.raises(ValueError, match="uv.lock"):
        check_sources(release_root)


@pytest.mark.parametrize(
    "changelog",
    [
        "## [Unreleased]\n- Notes.\n",
        "## [1.4.1]\n- Notes.\n",
        "## [1.4.1] - 2026-02-30\n- Notes.\n",
        "## [1.4.1] - 2026-09-24\n### Fixed\n",
        "## [1.4.2] - 2026-09-24\n- New.\n## [1.4.1] - 2026-09-23\n- Old.\n",
        "## [1.4.1] - 2026-09-24\n- First.\n## [1.4.1] - 2026-09-24\n- Duplicate.\n",
    ],
)
def test_reject_missing_or_invalid_release_notes(release_root, changelog):
    (release_root / "CHANGELOG.md").write_text(changelog)
    with pytest.raises(ValueError):
        check_sources(release_root)


@pytest.mark.parametrize(
    "overrides", [{"wheel_version": "1.4.0"}, {"sdist_version": "1.4.0"}, {"name": "other"}]
)
def test_reject_mislabeled_artifact_metadata(tmp_path, overrides):
    make_artifacts(tmp_path, **overrides)
    with pytest.raises(ValueError, match="embedded Name/Version"):
        check_artifacts(tmp_path, "redress", "1.4.1")


def test_reject_stale_extra_artifact(tmp_path):
    make_artifacts(tmp_path)
    (tmp_path / "redress-1.4.0.tar.gz").write_bytes(b"stale")
    with pytest.raises(ValueError, match="exactly one"):
        check_artifacts(tmp_path, "redress", "1.4.1")


def test_uv_build_bookkeeping_is_not_an_artifact(tmp_path):
    make_artifacts(tmp_path)
    (tmp_path / ".gitignore").write_text("*")
    check_artifacts(tmp_path, "redress", "1.4.1")


@pytest.mark.parametrize("missing", ["redress-1.4.1-py3-none-any.whl", "redress-1.4.1.tar.gz"])
def test_reject_missing_distribution(tmp_path, missing):
    make_artifacts(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(ValueError, match="exactly one"):
        check_artifacts(tmp_path, "redress", "1.4.1")


def test_reject_old_version_in_artifact_filename(tmp_path):
    make_artifacts(tmp_path)
    (tmp_path / "redress-1.4.1.tar.gz").rename(tmp_path / "redress-1.4.0.tar.gz")
    with pytest.raises(ValueError, match="filename"):
        check_artifacts(tmp_path, "redress", "1.4.1")


def test_cli_fails_before_publication_on_mismatch(release_root):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(release_root), "--tag", "v1.4.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "does not match" in result.stderr
