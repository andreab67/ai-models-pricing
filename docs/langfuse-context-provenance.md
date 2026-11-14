# Extractor context provenance

Model pricing is a prompts-only application. Each Kilo extraction captures the
exact local system instruction, wire response_format JSON and local Pydantic
validation schema before entering the HTTP client. The same immutable snapshot
supplies the actual request and the native generation metadata. The local schema
is identified as local_validation_schema; it is not sent as a provider schema.
Page contents, model output and exception messages are excluded from telemetry.

The shared schema 1 identifies model-pricing, local source paths, full component
SHA-256 values and a local snapshot release ID. Native prompt versions remain
null until a registry mirror is verified. Optional LANGFUSE_PROJECT_ID is declared
deployment identity, not authentication evidence. Pricing reconstruction, sanity
bounds, normalization, YAML rendering, review emails and commit policy are unchanged.

Optional LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY authenticate this app's own
project. LANGFUSE_HOST must be https://langfuse.andrea-house.com. For its private
CA, set LANGFUSE_CA_FILE to a mounted verified PEM bundle. Missing keys initialize
nothing; malformed optional telemetry configuration disables tracing only.

The public OpenTelemetry SDK and HTTP/protobuf exporter are pinned to 1.45.2.
They send native Langfuse generation attributes to /api/public/otel/v1/traces
with project Basic authentication and x-langfuse-ingestion-version:4. Export is
asynchronous, queue 128, batch 16, timeout 2 seconds. The dedicated provider has
no automatic shutdown hook; the application joins only its own daemon shutdown
worker for at most 2 seconds. No global provider or unrelated callback is changed.
The Docker build installs the pinned dependencies from the canonical Python
lockfile and adds the private CA to the system trust bundle. Deployment owns the
project keys, identity and LANGFUSE_CA_FILE reference to that verified bundle.

Validation uses mock provider responses, an in-memory native exporter and a
stalled local OTLP receiver. No live extraction, pricing commit or email is run.

## Deployment activation

The deployment helper preserves operator-owned workload fields and explicitly
merges only the unprefixed `langfuse-context-tracing` Secret reference into the
`kilo-diff` container's `envFrom` list, last. A resource-version JSON Patch test
rejects concurrent changes, and a live readback verifies the reference. Explicit
operator `LANGFUSE_*` environment variables fail this step because they would
override the Secret. Other Secrets, schedules, suspension, containers and
annotations remain unchanged. This does not run the scheduled pricing task.

The final HTTPS health check accepts only HTTP 200. It retries 502/503/504 up to
five GET attempts, with a 20-second per-attempt limit and two seconds between
attempts (at most 108 seconds). Redirects, authorization and certificate errors
still fail immediately.
