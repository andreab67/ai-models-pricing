"""Evaluate rendered API ingress selectors against known and unrelated callers."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _matches(selector, labels):
    matched = all(labels.get(k) == v for k, v in selector.get("matchLabels", {}).items())
    for expression in selector.get("matchExpressions", []):
        assert expression["operator"] == "In", "extend fixture evaluator for other operators"
        matched = matched and labels.get(expression["key"]) in expression["values"]
    return matched


@pytest.mark.parametrize("namespace,labels,allowed", [
    ("model-pricing", {"app": "web"}, True),
    ("model-pricing", {"app": "unrelated"}, False),
    ("monitoring", {"app.kubernetes.io/name": "prometheus"}, True),
    ("monitoring", {"app.kubernetes.io/name": "grafana"}, False),
    ("model-speed", {"app": "api"}, True),
    ("model-speed", {"batch.kubernetes.io/job-name": "benchmark-123"}, True),
    ("unrelated", {"app": "web"}, False),
    ("unrelated", {"app.kubernetes.io/name": "prometheus"}, False),
])
def test_rendered_api_policy(namespace, labels, allowed):
    result = subprocess.run(  # noqa: S603 - fixed local-only rendering command
        [shutil.which("kubectl") or "/usr/local/bin/kubectl", "kustomize",
         str(ROOT / "k8s/overlays/prod")], check=True, capture_output=True, text=True,
    )
    policies = [d for d in yaml.safe_load_all(result.stdout) if d["kind"] == "NetworkPolicy"]
    assert len(policies) == 1
    policy = policies[0]
    assert policy["metadata"]["namespace"] == "model-pricing"
    assert policy["spec"]["podSelector"]["matchLabels"]["app"] == "api"
    assert policy["spec"]["policyTypes"] == ["Ingress"]
    ns_labels = {"kubernetes.io/metadata.name": namespace}
    peers = []
    for ingress in policy["spec"]["ingress"]:
        assert ingress["ports"] == [{"protocol": "TCP", "port": 8000}]
        peers.extend(ingress["from"])
    actual = any(
        _matches(p["namespaceSelector"], ns_labels) and _matches(p["podSelector"], labels)
        for p in peers
    )
    assert actual is allowed
