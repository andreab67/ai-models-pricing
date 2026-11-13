"""Public exporter lifecycle contract; no remote exports."""

import pytest


def test_missing_keys_do_not_initialize_telemetry(monkeypatch):
    from app import observability as obs

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(obs, "_runtime", None)
    monkeypatch.setattr(obs, "_initialized", False)
    monkeypatch.setattr(
        obs, "_build_runtime", lambda *args: pytest.fail("initialized without keys")
    )
    assert obs._get_runtime() is None


def test_exporter_settings_are_scoped_and_only_owned_exit_callback_is_registered(monkeypatch):
    import base64
    import ssl

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as exporters
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app import observability as obs

    seen, registered = [], []

    def exporter(**kwargs):
        seen.append(kwargs)
        return InMemorySpanExporter()

    monkeypatch.setattr(exporters, "OTLPSpanExporter", exporter)
    monkeypatch.setattr(obs, "_runtime", None)
    monkeypatch.setattr(obs, "_initialized", False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_HOST", obs.DEFAULT_HOST)
    ca = ssl.get_default_verify_paths().cafile or "/etc/ssl/certs/ca-certificates.crt"
    monkeypatch.setenv("LANGFUSE_CA_FILE", ca)
    monkeypatch.setattr(obs.atexit, "register", lambda callback: registered.append(callback))
    monkeypatch.setattr(
        obs.atexit, "unregister", lambda callback: pytest.fail("unregistered another owner")
    )
    runtime = obs._get_runtime()
    assert runtime is not None
    assert registered == [obs.shutdown]
    assert seen[0]["certificate_file"] == ca
    assert seen[0]["timeout"] == 2
    assert seen[0]["endpoint"] == obs.DEFAULT_HOST + "/api/public/otel/v1/traces"
    assert seen[0]["headers"]["x-langfuse-ingestion-version"] == "4"
    assert (
        seen[0]["headers"]["Authorization"]
        == "Basic " + base64.b64encode(b"public-test:secret-test").decode()
    )
    obs.shutdown()


def test_bad_ca_disables_optional_telemetry_without_provider_failure(tmp_path, monkeypatch):
    from app import observability as obs

    monkeypatch.setattr(obs, "_runtime", None)
    monkeypatch.setattr(obs, "_initialized", False)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_CA_FILE", str(tmp_path / "missing.pem"))
    assert obs._get_runtime() is None


def test_stalled_real_otlp_export_has_bounded_process_exit():
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent("""
        import atexit, threading, time
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from app import observability as obs
        entered = threading.Event()
        class Server(BaseHTTPRequestHandler):
            def do_POST(self):
                entered.set()
                time.sleep(10)
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        exporter = OTLPSpanExporter(
            endpoint='http://127.0.0.1:' + str(server.server_port), timeout=2)
        provider = TracerProvider(shutdown_on_exit=False)
        provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=128,
            max_export_batch_size=16, schedule_delay_millis=1, export_timeout_millis=2000))
        obs._runtime = (provider, provider.get_tracer('test'))
        obs._initialized = True
        atexit.register(lambda: print('unrelated-callback-preserved'))
        provider.get_tracer('test').start_span('safe-metadata-only').end()
        assert entered.wait(1)
        started = time.monotonic()
        obs.shutdown()
        assert time.monotonic() - started < 2.5
        print('bounded-shutdown-complete')
    """)
    result = subprocess.run(  # noqa: S603 -- fixed inline local fixture, no user input
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert "bounded-shutdown-complete" in result.stdout
    assert "unrelated-callback-preserved" in result.stdout
