"""Real Kustomize rendering and image-only rollout ordering, without cluster access."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
API = "gitlab.andrea-house.com:5050/root/model-pricing/api"
WEB = "gitlab.andrea-house.com:5050/root/model-pricing/web"
SHA = "a" * 40


def _render(tmp_path: Path, sha: str = SHA) -> subprocess.CompletedProcess[str]:
    helper = ROOT / "scripts/render-prod-overlay.sh"
    assert helper.is_file()
    return subprocess.run(  # noqa: S603 - fixed helper, test-controlled args
        [
            shutil.which("bash") or "/bin/bash",
            str(helper),
            API,
            WEB,
            sha,
            str(tmp_path / "rendered.yaml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _images(doc: dict) -> list[str]:
    if doc["kind"] == "Deployment":
        pod = doc["spec"]["template"]["spec"]
    elif doc["kind"] == "CronJob":
        pod = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    else:
        return []
    return [c["image"] for c in [*pod.get("initContainers", []), *pod["containers"]]]


def test_all_workload_images_render_at_full_sha_without_source_mutation(tmp_path: Path) -> None:
    before = {p: p.read_bytes() for p in (ROOT / "k8s").rglob("*.yaml")}
    proc = _render(tmp_path)
    assert proc.returncode == 0, proc.stderr
    docs = list(yaml.safe_load_all((tmp_path / "rendered.yaml").read_text()))
    images = [image for doc in docs for image in _images(doc)]
    assert len(images) == 6
    assert images.count(f"{API}:{SHA}") == 5
    assert images.count(f"{WEB}:{SHA}") == 1
    assert before == {p: p.read_bytes() for p in (ROOT / "k8s").rglob("*.yaml")}


@pytest.mark.parametrize("sha", ["", "abc12345", "g" * 40, "a" * 40 + "\nother"])
def test_renderer_refuses_non_commit_tags(tmp_path: Path, sha: str) -> None:
    proc = _render(tmp_path, sha)
    assert proc.returncode != 0
    assert not (tmp_path / "rendered.yaml").exists()


def test_manual_prod_overlay_pins_existing_digests() -> None:
    proc = subprocess.run(  # noqa: S603 - fixed kubectl argv
        [
            shutil.which("kubectl") or "/usr/local/bin/kubectl",
            "kustomize",
            str(ROOT / "k8s/overlays/prod"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    images = [image for doc in yaml.safe_load_all(proc.stdout) for image in _images(doc)]
    assert len(images) == 6
    assert all("@sha256:" in image and len(image.rsplit(":", 1)[1]) == 64 for image in images)


_FAKE_KUBECTL = """#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  rollout)
    if [ "$2" = status ] && [ "$FAIL_ROLLOUT" = 1 ]; then exit 1; fi ;;
  get)
    case "$2" in
      deployment/web) printf '%s' "$EXPECTED_WEB" ;;
      *) printf '%s' "$EXPECTED_API" ;;
    esac ;;
esac
"""


def _run_deploy(
    tmp_path: Path,
    fail_rollout: bool = False,
    invalid_metadata=None,
    fail_smoke=False,
    smoke_code="200",
):
    helper = ROOT / "scripts/deploy-prod.sh"
    assert helper.is_file()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "kubectl"
    fake.write_text(_FAKE_KUBECTL)
    fake.chmod(0o755)
    curl = bindir / "curl"
    curl.write_text(
        '#!/bin/bash\nprintf "curl %s\\n" "$*" >> "$CALL_LOG"\n'
        '[ "$FAIL_SMOKE" = 0 ] && printf "%s" "$SMOKE_CODE"\nexit "$FAIL_SMOKE"\n'
    )
    curl.chmod(0o755)
    api_ref = API + "@sha256:" + "d" * 64
    web_ref = WEB + "@sha256:" + "e" * 64
    for producer, digit in [("build-api", "d"), ("build-web", "e")]:
        payload = {
            "containerimage.digest": "sha256:" + digit * 64,
            "image.name": f"{API if producer == 'build-api' else WEB}:{SHA}",
        }
        filename = f"image-metadata-{producer}-1.json"
        if invalid_metadata is not None and invalid_metadata[0] == producer:
            case = invalid_metadata[1]
            if case == "prefix":
                filename = f"image-metadata-{producer}-other-1.json"
            elif case == "nonnumeric":
                filename = f"image-metadata-{producer}-bogus.json"
            elif case == "other":
                filename = "image-metadata-other-1.json"
            elif case == "repository":
                payload["image.name"] = "registry.invalid/other:" + SHA
            elif case == "commit":
                payload["image.name"] = (API if producer == "build-api" else WEB) + ":" + "b" * 40
            elif case == "missing_name":
                del payload["image.name"]
            elif case == "multiple":
                (tmp_path / f"image-metadata-{producer}-2.json").write_text(json.dumps(payload))
        (tmp_path / filename).write_text(json.dumps(payload))
    log = tmp_path / "calls.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "IMAGE_API": API,
        "IMAGE_WEB": WEB,
        "CI_COMMIT_SHA": SHA,
        "CI_PROJECT_DIR": str(ROOT),
        "DEPLOY_RENDERED_FILE": str(tmp_path / "rendered.yaml"),
        "CALL_LOG": str(log),
        "FAIL_ROLLOUT": "1" if fail_rollout else "0",
        "FAIL_SMOKE": "1" if fail_smoke else "0",
        "SMOKE_CODE": smoke_code,
        "EXPECTED_API": api_ref,
        "EXPECTED_WEB": web_ref,
    }
    proc = subprocess.run(  # noqa: S603 - fixed helper and test-owned command boundary
        [shutil.which("bash") or "/bin/bash", str(helper)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


@pytest.mark.parametrize("fail_rollout", [False, True])
def test_deploy_changes_only_images_and_waits_before_cronjobs(
    tmp_path: Path, fail_rollout: bool
) -> None:
    proc, calls = _run_deploy(tmp_path, fail_rollout)
    api_ref = API + "@sha256:" + "d" * 64
    assert f"set image deployment/api migrate={api_ref} api={api_ref} -n model-pricing" in calls
    assert all(c.startswith(("set image ", "rollout ", "get ", "curl ")) for c in calls)
    cron = [i for i, c in enumerate(calls) if c.startswith("set image cronjob/")]
    if fail_rollout:
        assert proc.returncode == 1
        assert cron == []
        assert sum("rollout undo " in c for c in calls) == 2
    else:
        assert proc.returncode == 0, proc.stderr
        assert len(cron) == 3
        assert max(i for i, c in enumerate(calls) if "rollout status " in c) < min(cron)
        assert not any("rollout undo" in c for c in calls)


@pytest.mark.parametrize("kind", ["Deployment", "CronJob"])
def test_real_kubectl_image_only_update_preserves_operator_fields(
    tmp_path: Path, kind: str
) -> None:
    pod = {
        "initContainers": [{"name": "migrate", "image": API + ":old"}],
        "containers": [
            {
                "name": "api",
                "image": API + ":old",
                "env": [
                    {"name": "OPERATOR_SETTING", "value": "keep-me"},
                ],
            }
        ],
    }
    template = {"metadata": {"annotations": {"operator.example/setting": "preserve"}}, "spec": pod}
    spec = (
        {"replicas": 3, "selector": {"matchLabels": {"app": "api"}}, "template": template}
        if kind == "Deployment"
        else {
            "schedule": "0 * * * *",
            "suspend": True,
            "jobTemplate": {"spec": {"template": template}},
        }
    )
    obj = {
        "apiVersion": "apps/v1" if kind == "Deployment" else "batch/v1",
        "kind": kind,
        "metadata": {"name": "example"},
        "spec": spec,
    }
    source = tmp_path / "workload.yaml"
    source.write_text(yaml.safe_dump(obj))
    ref = API + "@sha256:" + "d" * 64
    proc = subprocess.run(  # noqa: S603 - verified CLI, fixed local-only command
        [
            shutil.which("kubectl") or "/usr/local/bin/kubectl",
            "set",
            "image",
            "--local",
            "-f",
            str(source),
            f"migrate={ref}",
            f"api={ref}",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    changed = json.loads(proc.stdout)
    changed_template = (
        changed["spec"]["template"]
        if kind == "Deployment"
        else changed["spec"]["jobTemplate"]["spec"]["template"]
    )
    assert changed_template["metadata"]["annotations"] == template["metadata"]["annotations"]
    assert changed_template["spec"]["containers"][0]["env"] == pod["containers"][0]["env"]
    assert changed_template["spec"]["containers"][0]["image"] == ref
    assert changed_template["spec"]["initContainers"][0]["image"] == ref
    if kind == "Deployment":
        assert changed["spec"]["replicas"] == 3
    else:
        assert changed["spec"]["schedule"] == "0 * * * *"
        assert changed["spec"]["suspend"] is True


@pytest.mark.parametrize("producer", ["build-api", "build-web"])
@pytest.mark.parametrize(
    "case", ["prefix", "nonnumeric", "repository", "commit", "missing_name", "multiple", "other"]
)
def test_wrong_build_identity_stops_real_deploy_before_writes(tmp_path, producer, case):
    proc, calls = _run_deploy(tmp_path, invalid_metadata=(producer, case))
    assert proc.returncode != 0
    assert not any(
        token in f" {call} "
        for call in calls
        for token in (" apply ", " patch ", " set image ", " rollout ")
    )


@pytest.mark.parametrize("failure", [False, True])
def test_post_rollout_smoke_uses_bounded_public_proxy(tmp_path, failure):
    proc, calls = _run_deploy(tmp_path, fail_smoke=failure)
    smoke = [c for c in calls if c.startswith("curl ")]
    assert len(smoke) == 1
    assert "--fail" in smoke[0] and "--max-time 20" in smoke[0]
    assert "https://models.andrea-house.com/api/healthz" in smoke[0]
    assert calls[-1] == smoke[0]
    assert proc.returncode == (1 if failure else 0)


def test_rollout_failure_never_starts_http_smoke(tmp_path):
    proc, calls = _run_deploy(tmp_path, fail_rollout=True)
    assert proc.returncode == 1
    assert not any(c.startswith("curl ") for c in calls)


@pytest.mark.parametrize("status", ["302", "503"])
def test_post_rollout_rejects_non_200_status(tmp_path, status):
    proc, calls = _run_deploy(tmp_path, smoke_code=status)
    assert proc.returncode != 0
    assert calls[-1].startswith("curl ")
