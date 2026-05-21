## Dev Setup for kubeflow with iam and istio ambient

### Deployment

```bash
just -f setup.just setup
just -f setup.just create-admin "username" "email"
```

### Models

* istio-system
  * istio-k8s
* iam
  * hydra
  * kratos
  * login-ui
  * postgresql
  * self-signed-certs
  * traefik
* kubeflow
  * ingress
  * istio-beacon
  * jupyter-ui
  * jupyter-controller
  * kserve-controller
  * kubeflow-profiles
  * kubeflow-dashboard
  * oauth2-proxy
  * self-signed-certs
