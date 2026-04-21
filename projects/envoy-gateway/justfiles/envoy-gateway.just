# Envoy Gateway + Charmed Istio Ambient test environment
# Prereq: microk8s (with metallb, rbac, dns, hostpath-storage) + juju bootstrapped
#
# Usage:
#   just -f projects/envoy-gateway/justfiles/envoy-gateway.just istio-test-envoy-setup
#   just -f projects/envoy-gateway/justfiles/envoy-gateway.just istio-test-envoy-nuke

istio_channel := "dev/edge"
bookinfo_channel := "latest/stable"
envoy_gateway_version := "v1.6.3"
ns := "istio-test"

# ====================================================================
# SETUP
# ====================================================================

istio-test-envoy-setup: _deploy-charms _wait-charms _install-envoy-gateway _create-envoy-resources _enroll-proxy _add-policy
    #!/usr/bin/env bash
    set -euo pipefail
    GATEWAY_IP=$(kubectl get gateway envoy-gateway -n {{ns}} -o jsonpath='{.status.addresses[0].value}')
    ISTIO_IP=$(kubectl get gateway ingress -n {{ns}} -o jsonpath='{.status.addresses[0].value}')
    echo ""
    echo "Setup complete!"
    echo "  Envoy Gateway:  curl http://${GATEWAY_IP}/productpage"
    echo "  Istio Ingress:  curl http://${ISTIO_IP}/istio-test-productpage"

[private]
_deploy-charms:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Deploying Istio + Bookinfo charms..."
    juju add-model {{ns}}
    juju deploy istio-k8s istio --channel={{istio_channel}} --trust
    juju deploy istio-beacon-k8s beacon --channel={{istio_channel}} --trust
    juju deploy istio-ingress-k8s ingress --channel={{istio_channel}} --trust
    juju deploy bookinfo-productpage-k8s productpage --channel={{bookinfo_channel}} --trust
    juju deploy bookinfo-details-k8s details --channel={{bookinfo_channel}} --trust
    juju integrate productpage:details details:details
    juju integrate productpage:service-mesh beacon:service-mesh
    juju integrate details:service-mesh beacon:service-mesh
    juju integrate productpage:ingress ingress:ingress

[private]
_wait-charms:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Waiting for charms to settle..."
    timeout 1200 bash -c 'while ! juju status --format=json | jq -e "
        .applications | to_entries | length > 0 and
        all(.[]; .value.\"application-status\".current == \"active\")
    " > /dev/null 2>&1; do echo "  waiting..."; sleep 15; done'
    echo "  All charms active."

[private]
_install-envoy-gateway:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Installing Envoy Gateway {{envoy_gateway_version}}..."
    # Ensure Gateway API CRDs are present
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml
    # Install in istio-test so the proxy pod lands in the same namespace
    microk8s helm install eg oci://docker.io/envoyproxy/gateway-helm \
        --version {{envoy_gateway_version}} \
        --namespace {{ns}} \
        --wait
    kubectl wait --for=condition=Available deployment/envoy-gateway \
        -n {{ns}} --timeout=120s
    kubectl apply -f - <<'YAML'
    apiVersion: gateway.networking.k8s.io/v1
    kind: GatewayClass
    metadata:
      name: eg
    spec:
      controllerName: gateway.envoyproxy.io/gatewayclass-controller
    YAML
    kubectl wait --for=condition=Accepted gatewayclass/eg --timeout=60s

[private]
_create-envoy-resources:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Creating Gateway + HTTPRoute..."
    kubectl apply -f - <<'YAML'
    apiVersion: gateway.networking.k8s.io/v1
    kind: Gateway
    metadata:
      name: envoy-gateway
      namespace: istio-test
    spec:
      gatewayClassName: eg
      listeners:
      - name: http
        protocol: HTTP
        port: 80
    ---
    apiVersion: gateway.networking.k8s.io/v1
    kind: HTTPRoute
    metadata:
      name: productpage-envoy
      namespace: istio-test
    spec:
      parentRefs:
      - name: envoy-gateway
        sectionName: http
      rules:
      - matches:
        - path:
            type: PathPrefix
            value: /
        backendRefs:
        - name: productpage
          port: 9080
    YAML
    kubectl wait --for=condition=Programmed gateway/envoy-gateway \
        -n {{ns}} --timeout=120s
    kubectl wait --for=condition=Available \
        -n {{ns}} deployment \
        -l gateway.envoyproxy.io/owning-gateway-name=envoy-gateway \
        --timeout=120s

[private]
_enroll-proxy:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Enrolling Envoy proxy pod in ambient mesh..."
    DEPLOY=$(kubectl get deployment -n {{ns}} \
        -l gateway.envoyproxy.io/owning-gateway-name=envoy-gateway \
        -o jsonpath='{.items[0].metadata.name}')
    kubectl patch deployment -n {{ns}} "${DEPLOY}" --type=merge \
        -p '{"spec":{"template":{"metadata":{"labels":{"istio.io/dataplane-mode":"ambient"}}}}}'
    kubectl rollout status deployment/"${DEPLOY}" -n {{ns}} --timeout=120s

[private]
_add-policy:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Adding L4 AuthorizationPolicy for Envoy Gateway..."
    DEPLOY=$(kubectl get deployment -n {{ns}} \
        -l gateway.envoyproxy.io/owning-gateway-name=envoy-gateway \
        -o jsonpath='{.items[0].metadata.name}')
    SA=$(kubectl get deployment -n {{ns}} "${DEPLOY}" \
        -o jsonpath='{.spec.template.spec.serviceAccountName}')
    kubectl apply -f - <<EOF
    apiVersion: security.istio.io/v1
    kind: AuthorizationPolicy
    metadata:
      name: productpage-envoy-gateway-l4
      namespace: {{ns}}
    spec:
      action: ALLOW
      selector:
        matchLabels:
          app.kubernetes.io/name: productpage
      rules:
      - from:
        - source:
            principals:
            - cluster.local/ns/{{ns}}/sa/${SA}
        to:
        - operation:
            ports:
            - "9080"
    EOF
    echo "  Policy created for SA: ${SA}"

# ====================================================================
# NUKE
# ====================================================================

istio-test-envoy-nuke:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Destroying Juju model (takes everything in the namespace with it)..."
    juju destroy-model {{ns}} --force --destroy-storage --no-prompt
    echo "==> Cleaning up cluster-scoped leftovers..."
    kubectl delete gatewayclass eg --ignore-not-found
    kubectl delete mutatingwebhookconfiguration envoy-gateway-topology-injector.{{ns}} --ignore-not-found
    kubectl get crd -o name | grep -E 'envoyproxy\.io|x-k8s\.io|backendtlspolicies|tcproutes|tlsroutes|udproutes' | xargs -r kubectl delete --ignore-not-found
    kubectl get clusterrole,clusterrolebinding -o name | grep 'eg-gateway-helm' | xargs -r kubectl delete --ignore-not-found
    echo "Done."
