# Continuous Deployment (CD) — Helm + Kubernetes

CD ทำงานอัตโนมัติผ่าน GitHub Actions เมื่อ push ไป branch หลัก:

| Branch   | Target       | Namespace               | Helm values file                  |
|----------|--------------|-------------------------|-----------------------------------|
| `develop`| Staging      | `log-management-staging`| `helm/log-management/values-staging.yaml` |
| `main`   | Production   | `log-management`        | `helm/log-management/values-prod.yaml`     |

ทุก push ที่ผ่าน Test + Security Scan + Build & Push จะ trigger deploy ตาม branch โดยอัตโนมัติ (ไม่มี approval gate — push = deploy)

---

## Flow

```
push ──▶ Test ──▶ Security Scan ──▶ Build & Push ──┬──▶ Deploy Staging   (develop)
                                                    └──▶ Deploy Production (main)
```

Image tags ใช้ `<branch>-<sha>` (เช่น `main-abc1234`, `develop-def5678`) เพื่อ traceability ทุก release rollback ได้ชัดเจน

---

## Required GitHub Secrets

ตั้งใน **Settings → Secrets and variables → Actions** (ทั้ง repo หรือ environment)

| Secret | Required by | Purpose |
|---|---|---|
| `KUBECONFIG` | Both | Base64-encoded kubeconfig ที่มีสิทธิ์ deploy ใน cluster (เช่น cluster-admin หรือ namespace-scoped role) |
| `SECRET_KEY` | Both | JWT signing key ≥ 32 chars — `openssl rand -hex 32` |
| `STAGING_DATABASE_URL` | Staging | Postgres URL สำหรับ staging namespace |
| `PROD_DATABASE_URL` | Production | Postgres URL สำหรับ production (managed RDS/Cloud SQL) |

> `GITHUB_TOKEN` ใช้สร้าง `ghcr-pull-secret` อัตโนมัติใน deploy job (มี `packages: read` permission เป็น default)

---

## One-time cluster setup

### 1) Install cert-manager (ใช้สำหรับ Let's Encrypt)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml

# Staging issuer (สำหรับ staging namespace)
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: ops@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
EOF

# Production issuer
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
      - http01:
          ingress:
            class: nginx
EOF
```

### 2) สร้าง ServiceAccount + RBAC สำหรับ GitHub Actions

```bash
# Staging namespace
kubectl create namespace log-management-staging
kubectl -n log-management-staging create serviceaccount github-actions-deploy
kubectl create rolebinding github-actions-deploy \
  --clusterrole=admin \
  --serviceaccount=log-management-staging:github-actions-deploy \
  --namespace=log-management-staging

# Production namespace
kubectl create namespace log-management
kubectl -n log-management create serviceaccount github-actions-deploy
kubectl create rolebinding github-actions-deploy \
  --clusterrole=admin \
  --serviceaccount=log-management:github-actions-deploy \
  --namespace=log-management
```

> ถ้าจะใช้ cluster-wide ให้แทน `rolebinding` ด้วย `clusterrolebinding --clusterrole=cluster-admin`

### 3) Generate kubeconfig แล้ว base64-encode

```bash
# Staging
SA_NAME=github-actions-deploy
NAMESPACE=log-management-staging
SERVER=https://<cluster-api-endpoint>  # จาก `kubectl cluster-info`
CLUSTER_NAME=$(kubectl config view --minify -o jsonpath='{.clusters[0].name}')

SECRET=$(kubectl -n $NAMESPACE get sa $SA_NAME -o jsonpath='{.secrets[0].name}')
TOKEN=$(kubectl -n $NAMESPACE get secret $SECRET -o jsonpath='{.data.token}' | base64 -d)
CA=$(kubectl -n $NAMESPACE get secret $SECRET -o jsonpath='{.data.ca\.crt}')

cat > kubeconfig.yml <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: $CLUSTER_NAME
    cluster:
      server: $SERVER
      certificate-authority-data: $CA
contexts:
  - name: github-actions
    context:
      cluster: $CLUSTER_NAME
      namespace: $NAMESPACE
      user: github-actions
current-context: github-actions
users:
  - name: github-actions
    user:
      token: $TOKEN
EOF

# ตรวจสอบก่อน encode
kubectl --kubeconfig=kubeconfig.yml get ns

# Encode
base64 < kubeconfig.yml | tr -d '\n' > kubeconfig.b64
# copy เนื้อหาใน kubeconfig.b64 → GitHub Secret `KUBECONFIG`
```

### 4) ตั้ง secrets ที่เหลือ

```bash
openssl rand -hex 32 | xargs -I {} echo "SECRET_KEY={}"

# Staging DB
echo "STAGING_DATABASE_URL=postgresql+asyncpg://user:pass@staging-db.example.com:5432/logs"

# Production DB
echo "PROD_DATABASE_URL=postgresql+asyncpg://user:pass@prod-db.example.com:5432/logs"
```

---

## Deploy ครั้งแรก

Push ไป develop (staging) หรือ main (prod) แล้วดูที่ **Actions** tab:
- Test ✓ → Security Scan ✓ → Build & Push ✓ → Deploy ✓
- Deploy job ใช้เวลา ~3–5 นาที (ครั้งแรกจะนานกว่าเพราะ `helm dependency update` ต้อง download redis + ingress-nginx charts)

ตรวจหลัง deploy เสร็จ:

```bash
kubectl -n log-management get pods
kubectl -n log-management get svc
kubectl -n log-management get ingress
```

---

## Rollback

```bash
# ดู history
helm history log-management -n log-management

# Rollback ไป revision ที่ต้องการ
helm rollback log-management 3 -n log-management

# หรือ deploy เวอร์ชันเก่าโดยตรง
helm upgrade --install log-management helm/log-management \
  -n log-management \
  -f helm/log-management/values-prod.yaml \
  --set backend.image.tag=main-<previous-sha> \
  --set frontend.image.tag=main-<previous-sha>
```

---

## Manual deploy (ไม่ผ่าน CI)

```bash
# Setup
export KUBECONFIG=./kubeconfig.yml

# Staging
helm upgrade --install log-management helm/log-management \
  -n log-management-staging --create-namespace \
  -f helm/log-management/values-staging.yaml \
  --set backend.image.repository=ghcr.io/OWNER/REPO/backend \
  --set frontend.image.repository=ghcr.io/OWNER/REPO/frontend \
  --set backend.image.tag=develop-abc1234 \
  --set frontend.image.tag=develop-abc1234 \
  --set backend.env.SECRET_KEY=$(openssl rand -hex 32) \
  --set backend.env.DATABASE_URL=postgresql+asyncpg://...
```

---

## Image tag convention

| Tag | Pushed on | Pinned to |
|---|---|---|
| `main-<sha>` | Push to main | Production deploys |
| `develop-<sha>` | Push to develop | Staging deploys |
| `latest` | Push to main | (สำหรับ local `docker pull` เท่านั้น — ไม่ได้ใช้ใน CD) |

ทุก deploy ผูกกับ SHA เฉพาะ ดังนั้น rollback หรือ re-run deploy ที่ SHA เดิมจะได้ image เดิมเสมอ

---

## Troubleshooting

### `ImagePullBackOff` บน pod

ตรวจ `ghcr-pull-secret`:

```bash
kubectl -n log-management get secret ghcr-pull-secret -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
```

ถ้า token หมดอายุ ให้รัน deploy job ใหม่ (deploy step recreate secret ทุกครั้ง)

### `helm dependency update` fail

Chart dependencies (redis, ingress-nginx) ต้องโหลดจาก internet — ถ้า runner โดน block ให้ vendor charts ลง `helm/log-management/charts/` ด้วย:

```bash
helm dependency update helm/log-management/
helm dependency build helm/log-management/  # populate charts/ from Chart.lock
git add helm/log-management/charts/ helm/log-management/Chart.lock
```

### `deploy-prod` fail เพราะ secret ไม่ครบ

Deploy step จะ validate `PROD_DATABASE_URL` + `SECRET_KEY` ก่อน ถ้าขาดจะ exit 1 ทันทีพร้อม `::error::` annotation

### Backend pod crash หลัง deploy

```bash
kubectl -n log-management logs -l app=log-management-backend --tail=100
kubectl -n log-management describe pod -l app=log-management-backend
```

常见สาเหตุ: `SECRET_KEY` อ่อนเกินไป (backend/main.py ปฏิเสธ — ต้อง ≥ 32 chars เมื่อ `DEBUG=false`), `DATABASE_URL` ผิด, หรือ `ALLOWED_ORIGINS` ไม่ตรง ingress host
