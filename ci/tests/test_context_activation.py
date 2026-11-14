"""Exercise the actual deployment scripts with local Kubernetes/curl boundaries."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_health_waits_only_for_transient_gateway_status(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    state = tmp_path / "responses"
    log = tmp_path / "calls"
    curl = bindir / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import os,pathlib\n"
        "p=pathlib.Path(os.environ['RESPONSES']); values=p.read_text().splitlines()\n"
        "value=values.pop(0); p.write_text('\\n'.join(values))\n"
        "with open(os.environ['CALLS'],'a') as f: f.write(value+'\\n')\n"
        "print(value,end=''); raise SystemExit(22 if int(value)>=400 else 0)\n"
    )
    curl.chmod(0o755)
    sleep = bindir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    for codes, expected, count in [
        (["502", "503", "504", "200"], 0, 4),
        (["502"] * 5, 22, 5),
        (["302", "200"], 1, 1),
        (["401", "200"], 22, 1),
        (["000", "200"], 1, 1),
    ]:
        state.write_text("\n".join(codes))
        log.write_text("")
        proc = subprocess.run(  # noqa: S603 - fixed local script; curl is fixture-owned
            [
                shutil.which("sh") or "/bin/sh",
                str(ROOT / "ci/healthcheck.sh"),
                "https://fixture.test/api/healthz",
            ],
            env={
                **os.environ,
                "PATH": f"{bindir}:{os.environ['PATH']}",
                "RESPONSES": str(state),
                "CALLS": str(log),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == expected, proc.stderr
        assert len(log.read_text().splitlines()) == count


def run_activation(tmp_path, *, conflict=False, explicit=False, absent=False):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    obj = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": "kilo-diff", "namespace": "model-pricing", "resourceVersion": "41"},
        "spec": {
            "schedule": "operator-schedule",
            "suspend": True,
            "jobTemplate": {
                "spec": {
                    "template": {
                        "metadata": {"annotations": {"operator": "retained"}},
                        "spec": {
                            "containers": [
                                {"name": "sidecar", "image": "sidecar:old"},
                                {
                                    "name": "diff",
                                    "image": "api:old",
                                    "env": [
                                        {
                                            "name": "LANGFUSE_PROJECT_ID"
                                            if explicit
                                            else "OPERATOR",
                                            "value": "keep",
                                        }
                                    ],
                                    "envFrom": [
                                        {"configMapRef": {"name": "operator"}},
                                        {
                                            "secretRef": {
                                                "name": "langfuse-context-tracing",
                                                "optional": True,
                                            }
                                        },
                                        {"secretRef": {"name": "other"}},
                                    ],
                                },
                            ],
                            "restartPolicy": "Never",
                        },
                    },
                }
            },
        },
    }
    if absent:
        del obj["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][1]["envFrom"]
    state = tmp_path / "state.json"
    state.write_text(json.dumps(obj))
    calls = tmp_path / "calls"
    real_kubectl = shutil.which("kubectl")
    assert real_kubectl
    fake = bindir / "kubectl"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,subprocess,sys\n"
        "args=sys.argv[1:]; state=pathlib.Path(os.environ['STATE'])\n"
        "with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(args)+'\\n')\n"
        "if args[:2]==['get','secret']:\n print('secret/langfuse-context-tracing')\n"
        "elif args[0]=='get':\n print(state.read_text())\n"
        "elif args[0]=='patch':\n"
        " if os.environ['CONFLICT']=='1':\n"
        "  obj=json.loads(state.read_text());obj['metadata']['resourceVersion']='42'\n"
        "  obj['spec']['suspend']=False;state.write_text(json.dumps(obj))\n"
        " patch=args[args.index('--patch-file')+1]\n"
        " result=subprocess.run([os.environ['REAL_KUBECTL'],'patch','--local','-f',str(state),"
        "'--type=json','--patch-file',patch,'-o','json'],capture_output=True,text=True)\n"
        " if result.returncode:\n"
        "  print(result.stderr,file=sys.stderr);raise SystemExit(result.returncode)\n"
        " state.write_text(result.stdout)\n"
        "else: raise SystemExit('unexpected boundary')\n"
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "STATE": str(state),
        "CALLS": str(calls),
        "REAL_KUBECTL": real_kubectl,
        "CONFLICT": str(int(conflict)),
    }
    proc = subprocess.run(  # noqa: S603 - real helper, local-only kubectl patch
        [shutil.which("bash") or "/bin/bash", str(ROOT / "scripts/activate-context-tracing.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc, obj, json.loads(state.read_text()), calls, env


@pytest.mark.parametrize("absent", [False, True])
def test_context_secret_is_last_and_operator_fields_survive_real_json_patch(tmp_path, absent):
    proc, before, after, calls, env = run_activation(tmp_path, absent=absent)
    assert proc.returncode == 0, proc.stderr
    containers = after["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    actual = containers[1].pop("envFrom")
    assert actual[-1] == {"secretRef": {"name": "langfuse-context-tracing"}}
    old = before["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][1].pop(
        "envFrom", []
    )
    assert actual[:-1] == [
        v for v in old if v.get("secretRef", {}).get("name") != "langfuse-context-tracing"
    ]
    assert after == before
    again = subprocess.run(  # noqa: S603 - same fixture-owned boundaries
        [shutil.which("bash") or "/bin/bash", str(ROOT / "scripts/activate-context-tracing.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert again.returncode == 0, again.stderr
    assert sum(json.loads(line)[0] == "patch" for line in calls.read_text().splitlines()) == 1


def test_revision_race_is_terminal_and_does_not_overwrite_concurrent_operator(tmp_path):
    proc, before, after, calls, _env = run_activation(tmp_path, conflict=True)
    assert proc.returncode != 0
    before["metadata"]["resourceVersion"] = "42"
    before["spec"]["suspend"] = False
    assert after == before
    assert sum(json.loads(line)[0] == "patch" for line in calls.read_text().splitlines()) == 1


def test_explicit_operator_langfuse_override_stops_before_patch(tmp_path):
    proc, before, after, calls, _env = run_activation(tmp_path, explicit=True)
    assert proc.returncode != 0
    assert after == before
    assert not any(json.loads(line)[0] == "patch" for line in calls.read_text().splitlines())
