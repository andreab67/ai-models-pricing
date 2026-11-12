"""Check each environment in a fresh interpreter, without a DB lifespan."""

import os
import subprocess
import sys

import pytest

SCRIPT = """
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
assert client.get('/healthz').status_code == 200
assert client.get('/docs').status_code == DOCS_STATUS
assert client.get('/openapi.json').status_code == DOCS_STATUS
response = client.options('/models', headers={
    'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'GET',
    'Access-Control-Request-Headers': 'accept,content-type',
})
assert response.status_code == 200
assert 'access-control-allow-credentials' not in response.headers
response = client.options('/models', headers={
    'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'GET',
    'Access-Control-Request-Headers': 'authorization',
})
assert response.status_code == 400
response = client.get('/healthz', headers={'Origin': 'http://localhost:3000'})
assert response.headers['access-control-allow-origin'] == 'http://localhost:3000'
assert 'access-control-allow-credentials' not in response.headers
assert client.options('/models', headers={
    'Origin': 'https://unrelated.invalid', 'Access-Control-Request-Method': 'GET',
}).status_code == 400
"""


@pytest.mark.parametrize("environment,status", [("prod", 404), ("staging", 404),
                                                 ("dev", 200), ("test", 200)])
def test_api_exposure_by_environment(environment, status):
    result = subprocess.run(  # noqa: S603 - fixed interpreter, isolated in-process ASGI calls
        [sys.executable, "-c", SCRIPT.replace("DOCS_STATUS", str(status))],
        env={**os.environ, "ENVIRONMENT": environment,
             "CORS_ORIGINS": '["http://localhost:3000"]'},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
