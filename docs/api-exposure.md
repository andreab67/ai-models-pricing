# API exposure and delivery checks

The browser uses the same-origin `/api/*` proxy. FastAPI permits GET CORS
requests from configured `CORS_ORIGINS`, with Accept and Content-Type headers,
without credential sharing. `/docs` and `/openapi.json` are available only when
`ENVIRONMENT` is `dev` or `test`. Health and catalog routes remain available.
Account proxy routes still require the existing explicit `EXPOSE_ACCOUNT_DATA`
opt-in behind owner-managed authentication. Transport failures are not cached.

The daily report exits nonzero when delivery returns false, including when SMTP
is unconfigured. Rendering a report alone does not count as successful delivery.
Cache cleanup runs on success and failure. No mail is sent by the test suite.

## NetworkPolicy activation gate

`k8s/base/api-networkpolicy.yaml` proposes ingress isolation for API pods on TCP
8000. It permits web pods in model-pricing, Prometheus pods in monitoring, and
pods in model-speed. The latter deliberately trusts the entire model-speed
namespace: its API Deployment and its benchmark CronJob consume the catalog,
and the benchmark template has no stable application label. This is not an
application-specific least-privilege boundary.

The web selector follows this repository's Deployment. The model-speed namespace
and unlabeled Job follow its current base manifests. The monitoring namespace
and Prometheus label follow Hermes `k8s/home/apply-kps.py` (`PDB_SELECTOR` and
Prometheus resource key). Before activation, the owner must read back current
namespace/pod labels, confirm CNI NetworkPolicy enforcement and all legitimate
callers, and approve the reviewed manifest. Offline rendered-selector tests
cannot establish live reachability. The peer selectors use expressions so
Kustomize commonLabels cannot impose model-pricing labels on external callers.

The image-only deployment script does not apply this new policy or other
operator-owned configuration. Activation remains a separate, explicit operation.
The deploy job sources the inherited internal CA into an additive public-root bundle
and verifies the HTTPS endpoint before any workload mutation; missing or unusable
trust fails the job at that point. Both checks require HTTP 200 and do not follow redirects.
It performs a bounded HTTP smoke request to the web proxy's
`/api/healthz` after required pipeline checks, successful rollouts, and image
verification. A smoke failure fails deployment; failed rollouts attempt both
undo operations, retain the original failure and never update CronJobs.

## Dependency verification

Jinja2 is pinned at 3.1.6 and aiosmtplib at 5.1.2 in the manifest and both
generated Python locks. The aiosmtplib update addresses the STARTTLS advisory
CVE-2026-55558. The runtime and dev Python closures install with hashes; frontend dev dependencies
are pinned to the versions already recorded in package-lock.json. The dev lock pins pytest 9.0.3, pytest-asyncio 1.4.1.post1 and pip 26.2 to address
tooling advisories and preserve plugin compatibility. Regeneration must use Python 3.14. Python wheel hashes do not make the entire image a hashed
closure: Debian packages installed through apt are authenticated by signed OS
repository metadata and can change as those repositories receive updates.
