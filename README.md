# DevOps Test Webserver — Platform Demo Console

A FastAPI service with a small web console, built for the VodafoneZiggo DevOps
O&Si assessment. It replaces the original static Nginx page with an application
that actually exercises the platform it runs on: every control in the UI produces
metrics in Mimir, logs in Loki and traces in Tempo.

## What it does

The console shows which pod served your request and gives you controls to drive
traffic through the cluster:

- **Serving pod** — pod, node, namespace, version, git SHA and uptime. Reload to
  watch requests round-robin across replicas.
- **Traffic controls** — generate load at a chosen latency, concurrency and CPU
  cost; fire deliberate errors; make a downstream call; inspect trace headers.
- **Readiness toggle** — mark the pod unready to demonstrate it dropping out of
  the Service endpoints without being restarted.
- **Session stats** — client-side request count, success/failure split and
  p50/p95 latency, for a quick read before you open Grafana.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | The web console |
| `GET /healthz` | Liveness probe — process is up |
| `GET /readyz` | Readiness probe — `503` when the pod is marked unready |
| `GET /metrics` | Prometheus exposition |
| `GET /docs` | OpenAPI documentation |
| `GET /api/info` | Build and pod identity |
| `GET /api/work?ms=&burn_ms=&jitter=` | Spend time awaiting I/O and/or burning CPU |
| `GET /api/error?code=&message=` | Return a deliberate error |
| `GET /api/echo` | Echo the request, highlighting trace-context headers |
| `GET /api/downstream?url=` | Make an outbound HTTP call (adds a span to the trace) |
| `POST /api/ready?ready=` | Toggle this pod's readiness flag |

`ms` is capped at 10s and `burn_ms` at 2s, so the demo controls cannot be used to
take the pod down.

## Prerequisites

- Python 3.13 (3.11+ works) for local development
- Docker (or Podman) to build the image

## Running Locally

### With Python

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app.main
```

### With Docker

```sh
docker build -t devops-test-webserver:latest .
docker run -p 8080:8080 devops-test-webserver:latest
```

Open `http://localhost:8080`.

The image is Debian-slim based and runs as non-root user `1001` on port `8080`,
making it compatible with OpenShift's arbitrary UID policy.

> **Why not Alpine?** The platform's OpenTelemetry operator injects its Python
> auto-instrumentation from an init container built against glibc. On a musl
> base that injection fails at runtime, so the smaller image would cost us the
> distributed tracing the cluster is built around.

## Configuration

All configuration is environment-based. Every value has a working default, so
the app runs with no configuration at all.

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `local` | `local` / `dev` / `stg` / `prod` — matches the GitOps directories |
| `APP_VERSION` | build arg | Reported on `/api/info` and `app_build_info` |
| `GIT_SHA` | build arg | Commit the image was built from |
| `LOG_LEVEL` | `INFO` | Root log level |
| `PORT` | `8080` | Listen port |
| `POD_NAME` / `NODE_NAME` / `NAMESPACE` | `local` | Set via the Downward API in the chart |
| `DOWNSTREAM_URL` | self | Target for `/api/downstream` |
| `DOWNSTREAM_TIMEOUT_SECONDS` | `5.0` | Downstream call timeout |

`APP_VERSION` and `GIT_SHA` are baked in at build time as defaults, but are read
from the environment at startup — so the release tag can be set by the Helm
chart without rebuilding the image (see *Releasing to Production* below).

## Observability

The app is designed against the platform's existing stack rather than shipping
its own agents:

- **Metrics** — `/metrics` exposes `http_requests_total`,
  `http_request_duration_seconds`, `http_requests_in_progress` and
  `app_build_info`. The `path` label is the *route template* (`/api/work`, not
  `/api/work?ms=250`), so query strings cannot inflate series cardinality.
- **Logs** — one JSON object per line on stdout, for Alloy to ship to Loki. When
  trace correlation is on, each line carries `trace_id` and `span_id`, linking a
  Loki line to its Tempo trace.
- **Traces** — there is deliberately **no OpenTelemetry SDK code in this repo**.
  The platform's operator injects it at admission when the pod carries:

  ```yaml
  annotations:
    instrumentation.opentelemetry.io/inject-python: "opentelemetry-operator/default"
  ```

  FastAPI, Starlette and httpx are then instrumented automatically. Adding the
  SDK here would double-instrument and pin a version the operator also controls.

## Testing

```sh
ruff check .          # lint
ruff format --check . # formatting
pytest -q             # tests
```

## CI/CD Pipeline

The pipeline is defined in `.github/workflows/ci.yaml` and has two flows:

### Build (PR and main push)

Triggers on every pull request and push to `main`:

1. **Lint and test** — `ruff check`, `ruff format --check`, then `pytest`
2. **Build** — Docker image built locally via BuildKit for scanning
3. **Scan** — Trivy scans for CRITICAL/HIGH vulnerabilities (blocks on failure)
4. **Push** — multi-arch image pushed to `ghcr.io/<org>/repo-app:sha-<short-sha>`

The image is built once single-arch for the scan, then built and pushed for
`linux/amd64` and `linux/arm64` once it is known to be clean.

### Promote (git tag)

Triggers when a semver tag (`v*.*.*`) is pushed:

1. **Scan** — Trivy scans the existing `sha-<sha>` image
2. **Promote** — image is retagged and pushed to `ghcr.io/<org>/repo-app-release:<tag>`

No rebuild — the promote step copies the already-built image, so the released
bits are byte-identical to the tested ones.

### Image Registries

| Registry | Tag format | Purpose |
|---|---|---|
| `ghcr.io/<org>/repo-app` | `sha-abc1234` | Non-release — PR testing, dev, staging |
| `ghcr.io/<org>/repo-app-release` | `v1.2.3` | Release — production deployments only |

### Releasing to Production

```sh
# After merging your PR to main and verifying the sha-tagged image:
git tag v1.0.0
git push origin v1.0.0
```

This triggers the promote job, which scans and copies the image to the release
repo. Update `prod/values.yaml` in the GitOps repo with the new tag, and set
`APP_VERSION` there to match — the promoted image is not rebuilt, so it carries
the build-time default until the chart overrides it.

## Deploying on OpenShift / Kubernetes

The image is deployed via ArgoCD using the [repo-app-gitops](https://github.com/vedantaggrawal/repo-app-gitops) repository. Each environment has its own `values.yaml`:

```
repo-app-gitops/apps/devops-test-webserver/
  local/values.yaml    # k3d/kind
  dev/values.yaml      # shared dev cluster
  stg/values.yaml      # staging
  prod/values.yaml     # production
```

To deploy manually with Helm:

```sh
helm install devops-test-webserver <path-to-helm-chart> \
  -f values.yaml \
  --set image.repository=ghcr.io/vedantaggrawal/repo-app \
  --set image.tag=sha-abc1234
```

### Running on Local Docker (without Kubernetes)

```sh
# Pull a specific build
docker pull ghcr.io/vedantaggrawal/repo-app:sha-abc1234

# Run it
docker run -p 8080:8080 ghcr.io/vedantaggrawal/repo-app:sha-abc1234
```

## CD — Local Infrastructure Bootstrap

The full local environment is provisioned with Terraform, which creates a Kind cluster, installs ArgoCD, and bootstraps the GitOps pipeline. Once bootstrapped, ArgoCD watches the gitops repos and auto-syncs all platform tools and applications.

### Architecture Overview

The setup spans five repositories:

| Repository | Purpose |
|---|---|
| [repo-app](https://github.com/vedantaggrawal/repo-app) | Application source code + CI pipeline |
| [repo-app-gitops](https://github.com/vedantaggrawal/repo-app-gitops) | Per-environment Helm values for apps |
| [repo-helm-chart](https://github.com/vedantaggrawal/repo-helm-chart) | Reusable generic Helm chart |
| [repo-platform-gitops](https://github.com/vedantaggrawal/repo-platform-gitops) | ArgoCD ApplicationSets + platform tool configs |
| [repo-platform](https://github.com/vedantaggrawal/repo-platform) | Terraform for Kind cluster + ArgoCD bootstrap |

### Prerequisites

Install the following before proceeding:

| Tool | Version | Install |
|---|---|---|
| Docker | Latest | [docs.docker.com/get-docker](https://docs.docker.com/get-docker/) |
| Terraform | >= 1.0 | `brew install terraform` |
| Kind | >= 0.20 | `brew install kind` |
| kubectl | >= 1.28 | `brew install kubectl` |
| Helm | >= 3.0 | `brew install helm` |
| Git | Latest | `brew install git` |

Verify all tools are available:

```sh
docker --version && terraform --version && kind --version && kubectl version --client && helm version && git --version
```

### GitHub Personal Access Token

Terraform needs a GitHub PAT to create Kubernetes secrets that allow ArgoCD to pull from your private repos.

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Generate a token with `repo` and `read:packages` scopes
3. Export it as an environment variable:

```sh
export TF_VAR_github_auth_token=ghp_your_token_here
```

### Provisioning the Cluster

```sh
cd repo-platform-infra/terraform-kind

# Initialise Terraform providers (kind, helm, kubernetes)
terraform init

# Preview what will be created
terraform plan

# Apply — creates the Kind cluster, installs ArgoCD, and bootstraps GitOps
terraform apply
```

Terraform performs these steps in order:

1. **Kind cluster** — Creates a cluster named `devops-local` with port mappings for ingress (80→10080, 443→10443)
2. **Namespaces** — Creates `argocd` and `devops-test-webserver` namespaces
3. **ArgoCD** — Installs ArgoCD via Helm into the `argocd` namespace
4. **Secrets** — Creates a Kubernetes secret with GitHub credentials for ArgoCD repo access
5. **Bootstrap** — Runs `kubectl apply -f bootstrap/local.yaml` which creates the root ArgoCD Application

### ArgoCD Bootstrap Flow

Once the root Application is created, ArgoCD takes over:

```
Root Application (bootstrap/local.yaml)
  └── argocd-apps Helm chart
        ├── ApplicationSet: platform-apps (sync wave -2 to -1)
        │     ├── metrics-server  (wave -2)
        │     ├── prometheus      (wave -1)
        │     └── traefik         (wave -1)
        └── ApplicationSet: apps (sync wave 0)
              └── devops-test-webserver
```

Sync waves ensure platform tools are healthy before applications deploy.

### Accessing ArgoCD

```sh
# Port-forward the ArgoCD server
kubectl port-forward svc/argocd-server -n argocd 8443:443

# Get the initial admin password
kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d
```

Open `https://localhost:8443` — login with username `admin` and the password above.

### Accessing the Application

Once ArgoCD syncs the `devops-test-webserver` app:

**Via Traefik Ingress (recommended)**

The local environment uses Traefik as ingress controller with host `local.webserver.internal`. The Kind cluster maps container ports 80→10080 and 443→10443 on the host.

Add the hostname to your `/etc/hosts` file:

```sh
echo "127.0.0.1 local.webserver.internal" | sudo tee -a /etc/hosts
```

> **Note:** Port 10080 (HTTP) may not work in browsers due to it being flagged as a non-standard port. Use HTTPS on port 10443 instead:

```
https://local.webserver.internal:10443
```

Your browser will show a certificate warning — click **Advanced** → **Proceed** (or "Accept the Risk") to continue with the self-signed certificate.

**Via port-forward (fallback)**

```sh
kubectl port-forward svc/devops-test-webserver -n devops-test-webserver 8080:8080
```

Open `http://localhost:8080` to reach the console.

### Tearing Down

```sh
cd repo-platform-infra/terraform-kind
terraform destroy
```

This removes the Kind cluster and all resources.

## Additional Considerations

- **Non-root**: The container runs as UID `1001` in the root group, with `/app`
  and the virtualenv group-accessible for OpenShift's arbitrary UID policy.
- **Multi-arch**: CI builds `linux/amd64` and `linux/arm64` images (Apple Silicon
  compatible). All dependencies ship manylinux wheels for both, so nothing is
  compiled under emulation.
- **Vulnerability scanning**: Trivy runs on every build and every promote.
  CRITICAL/HIGH findings block the pipeline. The runtime stage runs
  `apt-get upgrade` so the image picks up security fixes published since the base
  image was tagged.
- **No build step for the frontend**: the console is plain HTML, CSS and
  JavaScript, so the image ships exactly those bytes and adds no Node toolchain
  to the scan surface.
- **Single worker per pod**: scale with replicas rather than uvicorn workers,
  which keeps the Prometheus registry per-process and its counters correct.
- **GitOps**: ArgoCD watches the gitops repo and auto-syncs on `values.yaml`
  changes. Production changes require CODEOWNERS review.
