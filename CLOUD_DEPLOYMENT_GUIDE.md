# Cloud Deployment & CI/CD Guide

**Project:** Fault-Tolerant Distributed Lock Service Using Raft Consensus Algorithm  
**Application:** Distributed Cinema Seat-Booking & Real-Time Telemetry Monitor  

---

## 1. Cloud Architecture Overview

This project implements a hybrid architecture:
1. **Cloud Presentation Tier (Vercel):** The React 19 + Vite frontend deployed to Vercel as a publicly browsable, static single-page application (SPA).
2. **Cloud CI/CD & Registry (GitHub Actions + Docker Hub):**
   - GitHub Actions runs automated tests against a temporary cloud PostgreSQL service container on every commit/PR.
   - Upon successful test execution, GitHub Actions builds the production Docker image and publishes it to Docker Hub tagged with the commit SHA and `latest`.
3. **Consensus & State Engine (Local Docker Engine):**
   - The 3-node Raft consensus cluster (`raft-node-1:8001`, `raft-node-2:8002`, `raft-node-3:8003`) and transactional PostgreSQL database run locally via `docker-compose.yml`.
   - All state machine durability (WAL logs) and PostgreSQL database volumes remain intact and strictly local.

```
       +--------------------------------------------------------------+
       |                     GITHUB REPOSITORY                        |
       |  (git push / pull request on main/master)                    |
       +-------------------------------+------------------------------+
                                       |
                     Triggers CI/CD Workflow (.github/workflows/ci.yml)
                                       |
             +-------------------------+-------------------------+
             |                                                   |
             v                                                   v
   [Job 1: Backend Tests]                             [Job 2: Frontend Build]
   - Ephemeral PostgreSQL 16 Service                  - Node 20 / npm ci
   - Python 3.11 + pytest                             - Vite production compile
   - 52 core consensus tests                          - Verifies dist bundle
             |                                                   |
             +-------------------------+-------------------------+
                                       | (Both jobs succeed)
                                       v
                          [Job 3: Docker Build & Push]
                          - Builds backend/Dockerfile
                          - Authenticates via DOCKERHUB_TOKEN
                          - Publishes: <user>/raft-consensus-backend:latest
                                       <user>/raft-consensus-backend:sha-<sha>
```

---

## 2. Distinction: Vercel Frontend vs. Local Application

> [!IMPORTANT]
> **Understanding the Role of the Vercel Deployment:**
> - **Vercel Deployment:** Serves as a public showcase demonstrating modern cloud hosting, SPA compilation, and UI components. Because Vercel enforces HTTPS and our backend runs locally without exposing insecure public ports or tunnels, the Vercel-hosted deployment will not remotely trigger seat locks against your laptop.
> - **Local Application:** The complete, fully functional distributed consensus system (3 Raft nodes, leader election, lease expiration, distributed locks, database transactions, fault injection) runs locally via `docker compose up` and is demonstrated using `http://localhost:5173`.

---

## 3. Vercel – Frontend Deployment Instructions

### Prerequisites
- A free account on [Vercel](https://vercel.com) (sign up with GitHub).

### Steps to Deploy
1. Push your repository to GitHub.
2. Go to the **Vercel Dashboard** and click **"Add New..." -> "Project"**.
3. Import your GitHub repository (`acc_project_2`).
4. In the **Configure Project** screen, configure:
   - **Framework Preset:** `Vite` (auto-detected)
   - **Root Directory:** Click `Edit` and select `frontend`
   - **Build Command:** `npm run build` (default)
   - **Output Directory:** `dist` (default)
   - **Install Command:** `npm install` or `npm ci` (default)
5. Click **Deploy**.
6. The included `frontend/vercel.json` ensures that client-side SPA routing (e.g. `/monitor`) resolves directly to `index.html` without 404 errors.

---

## 4. GitHub Actions CI/CD Pipeline

The workflow is configured in [`.github/workflows/ci.yml`](file:///c:/Users/rithi/Downloads/acc_project_2/.github/workflows/ci.yml).

### How the Pipeline Works:
1. **`test-backend` Job:**
   - Spins up a clean, isolated `postgres:16-alpine` service container on the runner with health checks.
   - Installs Python 3.11 and packages from `requirements.txt`.
   - Executes 52 automated tests covering consensus elections, log replication, state machine locking, fencing tokens, and fault isolation.
   - **Zero dependency on your personal computer or local database.**
2. **`build-frontend` Job:**
   - Runs in parallel on `ubuntu-latest`.
   - Sets up Node.js 20, runs `npm ci`, and verifies `npm run build`.
3. **`docker-publish` Job:**
   - Runs only after both `test-backend` and `build-frontend` pass.
   - Builds the backend Docker image using `backend/Dockerfile`.
   - Tags the image with `latest` and `sha-<commit-sha>`.
   - Pushes to Docker Hub when secrets are configured.

---

## 5. Docker Hub – Cloud Container Registry Setup

### Required GitHub Repository Secrets
To allow GitHub Actions to publish built images to Docker Hub:

1. Log in to [Docker Hub](https://hub.docker.com).
2. Go to **Account Settings -> Security -> Access Tokens** and click **"New Access Token"**.
   - Description: `github-actions-ci`
   - Access permissions: `Read & Write`
   - Copy the generated Personal Access Token (PAT).
3. In your GitHub repository:
   - Go to **Settings -> Secrets and variables -> Actions**.
   - Click **"New repository secret"** and add:
     - Name: `DOCKERHUB_USERNAME`  
       Value: Your Docker Hub username (e.g., `johndoe`)
     - Name: `DOCKERHUB_TOKEN`  
       Value: The Personal Access Token copied in step 2.

> [!NOTE]
> If these secrets are not yet added, the pipeline gracefully detects their absence: it compiles and validates the Docker build on GitHub Actions without failing the build.

---

## 6. How to Trigger and Verify the Pipeline

1. **Commit and Push:**
   ```bash
   git add .
   git commit -m "feat: add Vercel SPA routing, GitHub Actions CI/CD and Docker Hub registry"
   git push origin main
   ```
2. **Verify in GitHub:**
   - Navigate to the **Actions** tab in your GitHub repository.
   - Click on the running workflow: **"CI/CD Pipeline & Docker Registry"**.
   - Confirm that:
     - `Backend Tests & Consensus Verification` succeeds with all 52 tests passing.
     - `Frontend Build Verification` succeeds.
     - `Docker Hub Image Build & Push` succeeds.
3. **Verify in Docker Hub:**
   - Open Docker Hub and verify that `<your-username>/raft-consensus-backend` has been published with tags `latest` and `sha-<short-sha>`.

---

## 7. Free-Tier Limitations Summary

| Platform | Cost | Free Tier Quotas | Viva Considerations |
| :--- | :--- | :--- | :--- |
| **Vercel** | $0 (Free) | 100 GB bandwidth / mo | Hosted on HTTPS; acts as a static UI showcase. |
| **GitHub Actions** | $0 (Free) | 2,000 minutes/month for private repos (Unlimited for public repos) | Isolated ephemeral PostgreSQL runner for tests; runs in ~2 minutes. |
| **Docker Hub** | $0 (Free) | Unlimited public repositories | Stores published backend images for automated distribution. |
| **Local Docker** | $0 (Free) | Uses local machine resources | Complete live consensus engine, fault injection, and PostgreSQL data persistence. |
