# DevOps Test Webserver

Lightweight, dockerized Nginx webserver built for the VodafoneZiggo DevOps O&Si assessment. Displays a greeting with a dynamic client-side timestamp.

## Prerequisites

- Docker (or Podman)
- GitHub account with access to GHCR (`ghcr.io`)

## Building the Docker Image Locally

```sh
docker build -t devops-test-webserver:latest .
```

The image is based on `nginx:alpine` and runs as non-root user `1001` on port `8080`, making it compatible with OpenShift's arbitrary UID policy.

## Running Locally

```sh
docker run -p 8080:8080 devops-test-webserver:latest
```

Open `http://localhost:8080` — you should see the greeting and your local time.

### Environment Variables

No environment variables are required. The webserver serves static HTML with client-side JavaScript for the timestamp.

### Nginx Configuration

Custom config is in `nginx/default.conf`. It listens on `8080` (non-privileged port) and serves from `/usr/share/nginx/html`.

## CI/CD Pipeline

The pipeline is defined in `.github/workflows/ci.yaml` and has two flows:

### Build (PR and main push)

Triggers on every pull request and push to `main`:

1. **Lint** — `htmlhint` validates `src/index.html`
2. **Build** — Docker image built locally via BuildKit
3. **Scan** — Trivy scans for CRITICAL/HIGH vulnerabilities (blocks on failure)
4. **Push** — Image pushed to `ghcr.io/<org>/repo-app:sha-<short-sha>`

### Promote (git tag)

Triggers when a semver tag (`v*.*.*`) is pushed:

1. **Scan** — Trivy runs SAST on the existing `sha-<sha>` image
2. **Promote** — Image is retagged and pushed to `ghcr.io/<org>/repo-app-release:<tag>`

No rebuild — the promote step copies the already-built image to the release registry.

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

This triggers the promote job, which scans and copies the image to the release repo. Update `prod/values.yaml` in the GitOps repo with the new tag.

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

The setup spans four repositories:

| Repository | Purpose |
|---|---|
| `repo-app` | Application source code + CI pipeline |
| `repo-app-gitops` | Per-environment Helm values for apps |
| `repo-platform-gitops` | ArgoCD ApplicationSets + platform tool configs |
| `repo-platform-infra` | Terraform for Kind cluster + ArgoCD bootstrap |

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

Open `http://localhost:8080` to see the greeting page.

### Tearing Down

```sh
cd repo-platform-infra/terraform-kind
terraform destroy
```

This removes the Kind cluster and all resources.

## Additional Considerations

- **Non-root**: The container runs as UID `1001`. All Nginx writable paths (`/var/run/nginx.pid`, `/var/cache/nginx`, `/var/log/nginx`) are group-writable for OpenShift compatibility.
- **Multi-arch**: CI builds `linux/amd64` and `linux/arm64` images (Apple Silicon compatible).
- **Vulnerability scanning**: Trivy runs on every build and on every promote. CRITICAL/HIGH findings block the pipeline.
- **GitOps**: ArgoCD watches the gitops repo and auto-syncs on `values.yaml` changes. Production changes require CODEOWNERS review.
