# Manual Test Guide – Auth Setup

## ✅ Prerequisites

Ensure the following environment is prepared before running the tests:

- A **Juju controller (v3.1+)** bootstrapped on a **MicroK8s** cluster
- **MetalLB** enabled on the MicroK8s cluster with a pool that has **at least 2 available IP addresses**

### MetalLB Setup

If MetalLB is **not yet enabled**, use:

```bash
sudo microk8s enable metallb:10.64.140.43-10.64.140.49
```

If MetalLB was enabled with only a single IP address, reset it using:

```bash
sudo microk8s disable metallb
sudo microk8s enable metallb:10.64.140.43-10.64.140.49
```

> Ensure the IP range has at least 2 available IPs for the ingress charms to bind.

---

## 🧪 Running the Test

To set up and deploy the full environment, run:

```bash
tox -e auth-setup -- --keep-models
```

This will spin up **3 Juju models**:

- `istio-system`: Hosts the Istio core components.
- `iam`: Hosts IAM-related components (Hydra, Kratos, Login UI, PostgreSQL).
- `ingress`: Hosts:
  - `istio-ingress-admin` & `istio-ingress-public` charms
  - `oauth2-proxy` charm (authentication gateway)
  - `self-signed-certificates` charm (TLS)
  - Two `catalogue` charms:
    - `catalogue-authed`: behind OAuth2-authenticated ingress
    - `catalogue-unauthed`: behind unauthenticated ingress

---

## 👤 Create a User for Authentication

Once deployment is complete, create a test user in Kratos using:

```bash
juju run -m iam kratos/0 create-admin-account email=test@example.com password=test username=admin
```

This will return:
- A **recovery code**
- A **link to set a new password**

>  Follow the link in a browser, create a password, and complete the 2FA setup using a 2FA app like **Google Authenticator**.

---

## 🔍 Test the Ingress Behavior

### 1. Unauthenticated Catalogue Page

Visit the following URL in your browser:

```
https://<public-ingress-ip>/ingress-catalogue-unauthed
```

✅ You should reach the catalogue page **without authentication**.

### 2. Authenticated Catalogue Page

Now go to:

```
https://<public-ingress-ip>/ingress-catalogue-authed
```

✅ This will redirect you to the **OAuth2 login page**.

- Use the credentials you set earlier (`test@example.com` + your password + 2FA code)
- After login, you’ll be redirected to the **authenticated catalogue** page