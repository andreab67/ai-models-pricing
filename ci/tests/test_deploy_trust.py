"""Real curl verification of the deploy job's CA preflight."""

import http.server
import os
import shutil
import ssl
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_real_curl_enforces_ca_and_hostname_with_deploy_trust(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    wrong = tmp_path / "wrong.pem"
    wrong_key = tmp_path / "wrong-key.pem"
    for name, cert_path, key_path in [("localhost", cert, key), ("wrong", wrong, wrong_key)]:
        subprocess.run(  # noqa: S603 - fixture-owned paths and fixed CLI
            [
                shutil.which("openssl") or "/usr/bin/openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
                "-days",
                "1",
                "-subj",
                f"/CN={name}",
                "-addext",
                f"subjectAltName=DNS:{name}",
            ],
            capture_output=True,
            check=True,
        )

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status = {"/": 200, "/redirect": 302, "/error": 503}[self.path]
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/login")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def request(ca, host, path="/", smoke=False):
            env = {
                **os.environ,
                "ADDITIONAL_CA_CERT_BUNDLE": ca.read_text(),
                "NO_PROXY": "localhost,127.0.0.1",
                "no_proxy": "localhost,127.0.0.1",
            }
            command = 'set -e; source "$1" "$2"; touch "$3"'
            helper = ROOT / "ci/prepare-deploy-trust.sh"
            if smoke:
                command = 'set -e; source "$1"; sh "$4" "$2"; touch "$3"'
                helper = ROOT / "ci/trust-registry.sh"
            return subprocess.run(  # noqa: S603 - fixed helper and local fixture
                [
                    shutil.which("bash") or "/bin/bash",
                    "-c",
                    command,
                    "bash",
                    str(helper),
                    f"https://{host}:{server.server_port}{path}",
                    str(tmp_path / "mutated"),
                    str(ROOT / "ci/healthcheck.sh"),
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        good = request(cert, "localhost")
        assert (tmp_path / "mutated").exists()
        (tmp_path / "mutated").unlink()
        redirect = request(cert, "localhost", "/redirect")
        assert redirect.returncode != 0
        assert not (tmp_path / "mutated").exists()
        error = request(cert, "localhost", "/error")
        assert error.returncode != 0
        assert not (tmp_path / "mutated").exists()
        smoke_good = request(cert, "localhost", smoke=True)
        assert smoke_good.returncode == 0
        assert (tmp_path / "mutated").exists()
        (tmp_path / "mutated").unlink()
        for path in ("/redirect", "/error"):
            result = request(cert, "localhost", path, smoke=True)
            assert result.returncode != 0
            assert not (tmp_path / "mutated").exists()
        bad_ca = request(wrong, "localhost")
        assert not (tmp_path / "mutated").exists()
        bad_host = request(cert, "127.0.0.1")
        assert not (tmp_path / "mutated").exists()
        assert good.returncode == 0, good.stderr
        assert bad_ca.returncode == 60 and "certificate" in bad_ca.stderr.lower()
        assert bad_host.returncode == 60 and (
            "subject" in bad_host.stderr.lower() or "hostname" in bad_host.stderr.lower()
        )
        bundle = Path("/tmp/registry-ca-bundle.pem").read_bytes()  # noqa: S108 - actual CI bundle
        assert bundle.startswith(Path("/etc/ssl/certs/ca-certificates.crt").read_bytes())
        assert cert.read_bytes().strip() in bundle
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_missing_or_malformed_ca_stops_before_mutation(tmp_path):
    for value in (None, "not a certificate"):
        env = os.environ.copy()
        env.pop("ADDITIONAL_CA_CERT_BUNDLE", None)
        if value is not None:
            env["ADDITIONAL_CA_CERT_BUNDLE"] = value
        marker = tmp_path / "mutated"
        result = subprocess.run(  # noqa: S603 - fixed script and fixture marker
            [
                shutil.which("bash") or "/bin/bash",
                "-c",
                'set -e; source "$1" https://localhost:1/; touch "$2"',
                "bash",
                str(ROOT / "ci/prepare-deploy-trust.sh"),
                str(marker),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert not marker.exists()


def test_ci_runs_preflight_before_deploy():
    import yaml

    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
    commands = ci["deploy:k8s"]["script"]
    preflight = "source ci/prepare-deploy-trust.sh https://models.andrea-house.com/api/healthz"
    assert commands.index(preflight) < commands.index("bash scripts/deploy-prod.sh")


def test_post_rollout_uses_same_status_check():
    deploy = (ROOT / "scripts/deploy-prod.sh").read_text()
    assert 'sh "$repo/ci/healthcheck.sh" https://models.andrea-house.com/api/healthz' in deploy
