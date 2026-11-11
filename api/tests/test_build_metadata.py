"""Read genuine BuildKit metadata only for the requested producer and image."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCER = "build-api"
IMAGE = "gitlab.andrea-house.com:5050/root/model-pricing/api"
SHA = "a" * 40
DIGEST = "sha256:" + "d" * 64


def metadata():
    return {"containerimage.digest": DIGEST, "image.name": f"{IMAGE}:{SHA}"}


def run_reader(tmp_path, producer=PRODUCER, image=IMAGE, sha=SHA):
    return subprocess.run(  # noqa: S603 - real helper, test-controlled arguments
        [
            shutil.which("sh") or "/bin/sh",
            str(ROOT / "ci/read-image-digest.sh"),
            producer,
            image,
            sha,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reads_exact_producer_numeric_job_and_expected_image(tmp_path):
    (tmp_path / f"image-metadata-{PRODUCER}-123.json").write_text(json.dumps(metadata()))
    proc = run_reader(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == DIGEST + "\n"


@pytest.mark.parametrize("suffix", ["other-123", "bogus", "123-other", "", "12x", "-123"])
def test_rejects_non_numeric_or_prefixed_producer_artifacts(tmp_path, suffix):
    (tmp_path / f"image-metadata-{PRODUCER}-{suffix}.json").write_text(json.dumps(metadata()))
    proc = run_reader(tmp_path)
    assert proc.returncode != 0
    assert proc.stdout == ""


@pytest.mark.parametrize(
    "identity",
    [
        None,
        "",
        123,
        [],
        "registry.invalid/other:" + SHA,
        IMAGE + ":" + "b" * 40,
        IMAGE + ":" + SHA[:8],
        IMAGE + "@" + DIGEST,
        IMAGE + ":" + SHA + "\n",
    ],
)
def test_rejects_missing_or_wrong_image_identity(tmp_path, identity):
    payload = metadata()
    if identity is None:
        del payload["image.name"]
    else:
        payload["image.name"] = identity
    (tmp_path / f"image-metadata-{PRODUCER}-123.json").write_text(json.dumps(payload))
    proc = run_reader(tmp_path)
    assert proc.returncode != 0
    assert proc.stdout == ""


@pytest.mark.parametrize(
    "digest", [None, "sha256:" + "g" * 64, "sha256:" + "a" * 63, [DIGEST], 123, DIGEST + "\n"]
)
def test_rejects_invalid_digest(tmp_path, digest):
    payload = metadata()
    payload["containerimage.digest"] = digest
    (tmp_path / f"image-metadata-{PRODUCER}-123.json").write_text(json.dumps(payload))
    proc = run_reader(tmp_path)
    assert proc.returncode != 0
    assert proc.stdout == ""


@pytest.mark.parametrize("contents", ["{broken", "null", "[]", "42", "{}", "multi_json"])
def test_requires_exactly_one_metadata_object(tmp_path, contents):
    if contents == "multi_json":
        contents = json.dumps(metadata()) + "\n" + json.dumps(metadata())
    (tmp_path / f"image-metadata-{PRODUCER}-123.json").write_text(contents)
    proc = run_reader(tmp_path)
    assert proc.returncode != 0
    assert proc.stdout == ""


@pytest.mark.parametrize("producers", [[], ["other"], [PRODUCER, PRODUCER]])
def test_rejects_missing_unrelated_or_multiple_files(tmp_path, producers):
    for job_id, producer in enumerate(producers, 1):
        (tmp_path / f"image-metadata-{producer}-{job_id}.json").write_text(json.dumps(metadata()))
    proc = run_reader(tmp_path)
    assert proc.returncode != 0
    assert proc.stdout == ""


@pytest.mark.parametrize(
    "producer,image,sha",
    [
        ("build-other/../../", IMAGE, SHA),
        (PRODUCER, "", SHA),
        (PRODUCER, IMAGE, SHA[:8]),
        (PRODUCER, IMAGE, "g" * 40),
    ],
)
def test_requires_explicit_valid_caller_identity(tmp_path, producer, image, sha):
    (tmp_path / f"image-metadata-{PRODUCER}-123.json").write_text(json.dumps(metadata()))
    proc = run_reader(tmp_path, producer, image, sha)
    assert proc.returncode != 0
    assert proc.stdout == ""
