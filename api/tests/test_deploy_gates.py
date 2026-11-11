"""Deploy gates: the pipeline graph and the secret scoping in the manifests.

These read the repo's own YAML (CI file and k8s manifests), so a change that
loosens a gate fails here before it reaches a pipeline.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CI_FILE = REPO / ".gitlab-ci.yml"
K8S_BASE = REPO / "k8s" / "base"
K8S_PROD = REPO / "k8s" / "overlays" / "prod"
TRIVYIGNORE = REPO / "web" / ".trivyignore"

SECRET = "model-pricing-secrets"  # noqa: S105 - a k8s Secret name, not a credential
GATING_JOBS = [
    "lint:web",
    "lint:api",
    "scan:api-image-trivy",
    "scan:web-image-trivy",
    "test:api",
    "test:db-migrations",
]

pytestmark = pytest.mark.skipif(
    not CI_FILE.exists() or not K8S_BASE.exists(),
    reason="repo-level files are not available (tests run outside the checkout)",
)


# --- CI pipeline graph -----------------------------------------------------


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return yaml.safe_load(CI_FILE.read_text())


def test_deploy_needs_builds_lints_scans_and_tests(ci: dict[str, Any]) -> None:
    needs = ci["deploy:k8s"]["needs"]
    names = {n if isinstance(n, str) else n["job"] for n in needs}
    assert {"build:api", "build:web", *GATING_JOBS} <= names


def test_every_deploy_need_is_a_defined_job(ci: dict[str, Any]) -> None:
    for n in ci["deploy:k8s"]["needs"]:
        assert (n if isinstance(n, str) else n["job"]) in ci


@pytest.mark.parametrize("job", GATING_JOBS)
def test_gating_jobs_cannot_fail_silently(ci: dict[str, Any], job: str) -> None:
    assert not ci[job].get("allow_failure", False)


@pytest.mark.parametrize(
    ("job", "image_var", "build"),
    [
        ("scan:api-image-trivy", "IMAGE_API", "build:api"),
        ("scan:web-image-trivy", "IMAGE_WEB", "build:web"),
    ],
)
def test_image_scans_are_blocking_and_scan_the_built_image_digest(
    ci: dict[str, Any], job: str, image_var: str, build: str
) -> None:
    spec = ci[job]
    assert spec["stage"] in ci["stages"]
    assert ci["stages"].index(spec["stage"]) > ci["stages"].index(ci[build]["stage"])
    assert build in spec["needs"]
    script = "\n".join(spec["script"])
    assert "--exit-code 1" in script
    assert "HIGH,CRITICAL" in script
    assert f"${{{image_var}}}@${{IMAGE_DIGEST}}" in script
    assert "--insecure" not in script
    assert f"read-image-digest.sh {build.replace(':', '-')}" in "\n".join(spec["before_script"])
    assert "--image-src remote" in script
    assert spec["variables"]["TRIVY_USERNAME"] == "$CI_REGISTRY_USER"
    assert spec["variables"]["TRIVY_PASSWORD"] == "$CI_REGISTRY_PASSWORD"  # noqa: S105
    # They must run wherever deploy:k8s's own pipeline runs.
    assert set(ci["deploy:k8s"]["only"]) <= set(spec["only"])


def test_web_scan_ignorefile_flag_and_file_stay_in_step(ci: dict[str, Any]) -> None:
    """The web runner ships no npm, so the scan needs no suppressions.

    If a suppression is ever re-added, the flag and the file must come
    together (a flag without a file, or a file nothing reads, is a silent gap).
    """
    script = "\n".join(ci["scan:web-image-trivy"]["script"])
    assert ("--ignorefile web/.trivyignore" in script) == TRIVYIGNORE.exists()


def test_web_runner_stage_drops_npm_corepack_and_yarn() -> None:
    dockerfile = (REPO / "web" / "Dockerfile").read_text()
    runner = dockerfile.split("AS runner", 1)[1]
    for needle in ("node_modules/npm", "node_modules/corepack", "/opt/yarn", "bin/npx"):
        assert needle in runner, needle
    # Only the final stage is stripped: the builder stages still need npm.
    assert "rm -rf /usr/local/lib/node_modules/npm" not in dockerfile.split("AS runner", 1)[0]


def test_api_runtime_stage_removes_pip_and_setuptools_and_upgrades_zlib() -> None:
    runtime = (REPO / "api" / "Dockerfile").read_text().split("AS runtime", 1)[1]
    assert "pip uninstall -y pip setuptools" in runtime
    assert "--only-upgrade zlib1g" in runtime


def test_trivyignore_entries_each_have_a_reason_and_a_valid_id() -> None:
    if not TRIVYIGNORE.exists():
        pytest.skip("no suppressions")
    lines = TRIVYIGNORE.read_text().splitlines()
    entries = 0
    for i, line in enumerate(lines):
        if not line.strip() or line.startswith("#"):
            continue
        entries += 1
        assert re.fullmatch(r"CVE-\d{4}-\d{4,}( exp:\d{4}-\d{2}-\d{2})?", line.strip()), line
        # A reason: the line directly above is a comment.
        assert i > 0 and lines[i - 1].startswith("#"), f"{line} has no reason comment"
    assert entries >= 1


# --- Secret scoping in the manifests ---------------------------------------


def _workloads(base: Path) -> list[tuple[str, dict[str, Any]]]:
    """(workload name, pod spec) for every Deployment and CronJob under ``base``."""
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(base.glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if not doc or "secret" in path.name:
                continue
            if doc["kind"] == "Deployment":
                out.append((doc["metadata"]["name"], doc["spec"]["template"]["spec"]))
            elif doc["kind"] == "CronJob":
                pod = doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                out.append((doc["metadata"]["name"], pod))
    return out


def _secret_keys(pod: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for c in [*pod.get("initContainers", []), *pod["containers"]]:
        for e in c.get("env", []):
            ref = (e.get("valueFrom") or {}).get("secretKeyRef")
            if ref and ref["name"] == SECRET:
                keys.add(ref["key"])
    return keys


def test_workloads_were_found() -> None:
    assert {n for n, _ in _workloads(K8S_BASE)} >= {
        "api",
        "web",
        "refresh-pricing",
        "daily-report",
        "kilo-diff",
    }


def test_no_workload_loads_the_whole_secret_with_envfrom() -> None:
    for name, pod in _workloads(K8S_BASE):
        for c in [*pod.get("initContainers", []), *pod["containers"]]:
            for source in c.get("envFrom", []):
                assert (source.get("secretRef") or {}).get("name") != SECRET, (name, c["name"])


def test_only_kilo_diff_references_gitlab_token() -> None:
    holders = {n for n, pod in _workloads(K8S_BASE) if "GITLAB_TOKEN" in _secret_keys(pod)}
    assert holders == {"kilo-diff"}


def test_gitlab_token_is_not_anywhere_else_in_the_manifests() -> None:
    for path in K8S_BASE.glob("*.yaml"):
        if path.name in ("cronjob-kilo-diff.yaml", "secret.example.yaml"):
            continue
        assert "GITLAB_TOKEN" not in path.read_text(), path.name


def _refs_by_container(pod: dict[str, Any]) -> dict[str, dict[str, bool]]:
    """container name -> {secret key: optional?} for model-pricing-secrets."""
    out: dict[str, dict[str, bool]] = {}
    for c in [*pod.get("initContainers", []), *pod["containers"]]:
        refs = {}
        for e in c.get("env", []):
            ref = (e.get("valueFrom") or {}).get("secretKeyRef")
            if ref and ref["name"] == SECRET:
                refs[ref["key"]] = bool(ref.get("optional", False))
        out[c["name"]] = refs
    return out


EXPECTED_KEYS: dict[tuple[str, str], set[str]] = {
    ("api", "migrate"): {"DATABASE_URL"},
    ("api", "api"): {
        "DATABASE_URL",
        "REDIS_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_ADMIN_KEY",
        "KILO_API_KEY",
        "KILO_TIER",
        "MINIMAX_API_KEY",
        "DEEPSEEK_API_KEY",
    },
    ("refresh-pricing", "refresh"): {"DATABASE_URL", "REDIS_URL", "OPENROUTER_API_KEY"},
    ("daily-report", "report"): {"REDIS_URL", "OPENROUTER_API_KEY", "KILO_TIER"},
    ("kilo-diff", "diff"): {"DATABASE_URL", "REDIS_URL", "OPENROUTER_API_KEY", "GITLAB_TOKEN"},
}


def test_each_container_gets_exactly_the_keys_it_uses() -> None:
    got = {
        (name, container): set(refs)
        for name, pod in _workloads(K8S_BASE)
        for container, refs in _refs_by_container(pod).items()
        if refs
    }
    assert got == EXPECTED_KEYS
    # web mounts nothing from the Secret at all.
    web = dict(_workloads(K8S_BASE))["web"]
    assert all(not refs for refs in _refs_by_container(web).values())


def test_only_database_url_and_gitlab_token_are_required() -> None:
    required = {
        (name, container, key)
        for name, pod in _workloads(K8S_BASE)
        for container, refs in _refs_by_container(pod).items()
        for key, optional in refs.items()
        if not optional
    }
    assert {key for _, _, key in required} == {"DATABASE_URL", "GITLAB_TOKEN"}
    assert {(n, c) for n, c, k in required if k == "GITLAB_TOKEN"} == {("kilo-diff", "diff")}


def test_scan_jobs_do_not_gate_the_test_jobs(ci: dict[str, Any]) -> None:
    """Scans run beside test:*, not in an earlier stage the tests would wait on."""
    stages = ci["stages"]
    assert "scan" not in stages
    for job in ("scan:api-image-trivy", "scan:web-image-trivy"):
        assert ci[job]["stage"] == ci["test:api"]["stage"]


def test_api_runtime_removes_pip_by_exact_path_not_a_glob() -> None:
    runtime = (REPO / "api" / "Dockerfile").read_text().split("AS runtime", 1)[1]
    assert "site-packages/pip*" not in runtime
    assert "site-packages/setuptools*" not in runtime
    for exact in (
        "site-packages/pip \\",
        "site-packages/pip-*.dist-info",
        "site-packages/setuptools \\",
        "site-packages/setuptools-*.dist-info",
        "site-packages/wheel \\",
    ):
        assert exact in runtime, exact


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_rendered_prod_overlay_has_gitlab_token_only_in_kilo_diff() -> None:
    rendered = subprocess.run(  # noqa: S603 - fixed argv, repo path
        [shutil.which("kubectl") or "kubectl", "kustomize", str(K8S_PROD)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    holders = set()
    for doc in yaml.safe_load_all(rendered):
        if not doc or doc["kind"] not in ("Deployment", "CronJob"):
            continue
        pod = (
            doc["spec"]["template"]["spec"]
            if doc["kind"] == "Deployment"
            else doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        )
        if "GITLAB_TOKEN" in _secret_keys(pod):
            holders.add(doc["metadata"]["name"])
        for c in [*pod.get("initContainers", []), *pod["containers"]]:
            for source in c.get("envFrom", []):
                assert (source.get("secretRef") or {}).get("name") != SECRET
    assert holders == {"kilo-diff"}


@pytest.mark.parametrize(
    "producer,image_var,job",
    [
        ("build-api", "IMAGE_API", "scan:api-image-trivy"),
        ("build-web", "IMAGE_WEB", "scan:web-image-trivy"),
    ],
)
@pytest.mark.parametrize(
    "case",
    ["valid", "prefix", "nonnumeric", "repository", "commit", "missing_name", "multiple", "other"],
)
def test_scan_validates_metadata_before_starting_trivy(
    tmp_path, ci, producer, image_var, job, case
):
    sha = "a" * 40
    image = "gitlab.andrea-house.com:5050/root/model-pricing/" + (
        "api" if image_var == "IMAGE_API" else "web"
    )
    digest = "sha256:" + "d" * 64
    payload = {"containerimage.digest": digest, "image.name": image + ":" + sha}
    filename = f"image-metadata-{producer}-1.json"
    if case == "prefix":
        filename = f"image-metadata-{producer}-other-1.json"
    elif case == "nonnumeric":
        filename = f"image-metadata-{producer}-bogus.json"
    elif case == "other":
        filename = "image-metadata-other-1.json"
    elif case == "repository":
        payload["image.name"] = "registry.invalid/other:" + sha
    elif case == "commit":
        payload["image.name"] = image + ":" + "b" * 40
    elif case == "missing_name":
        del payload["image.name"]
    elif case == "multiple":
        (tmp_path / f"image-metadata-{producer}-2.json").write_text(json.dumps(payload))
    (tmp_path / filename).write_text(json.dumps(payload))
    (tmp_path / "ci").symlink_to(REPO / "ci", target_is_directory=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in [
        ("apk", "#!/bin/sh\nexit 0\n"),
        ("trivy", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SCAN_LOG"\n'),
    ]:
        fake = bindir / name
        fake.write_text(body)
        fake.chmod(0o755)
    scan_log = tmp_path / "scan.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        image_var: image,
        "CI_COMMIT_SHA": sha,
        "ADDITIONAL_CA_CERT_BUNDLE": "public test CA fixture",
        "SCAN_LOG": str(scan_log),
    }
    spec = ci[job]
    script = "\n".join([*spec["before_script"], *spec["script"]])
    proc = subprocess.run(  # noqa: S603 - actual CI code, only package/network commands stubbed
        [shutil.which("bash") or "/bin/bash", "-e", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if case == "valid":
        assert proc.returncode == 0, proc.stderr
        assert image + "@" + digest in scan_log.read_text()
    else:
        assert proc.returncode != 0
        assert not scan_log.exists()
