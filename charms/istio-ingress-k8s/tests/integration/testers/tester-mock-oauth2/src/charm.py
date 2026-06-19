#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Mock OAuth2 server charm for integration testing."""
import base64
import json
import urllib.request

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, WaitingStatus
from ops.pebble import Layer

PORT = 8080


class MockOAuth2Charm(CharmBase):
    """Wraps navikt/mock-oauth2-server for JWT-based authentication testing."""

    def __init__(self, framework):
        super().__init__(framework)
        self.framework.observe(
            self.on.mock_oauth2_server_pebble_ready, self._on_pebble_ready
        )
        self.framework.observe(self.on.get_issuer_info_action, self._on_get_issuer_info)
        self.framework.observe(self.on.get_token_action, self._on_get_token)

    def _on_pebble_ready(self, _):
        container = self.unit.get_container("mock-oauth2-server")
        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        layer = Layer(
            {
                "summary": "mock-oauth2-server layer",
                "services": {
                    "mock-oauth2-server": {
                        "override": "replace",
                        "command": "java -cp @/app/jib-classpath-file no.nav.security.mock.oauth2.StandaloneMockOAuth2ServerKt",
                        "startup": "enabled",
                        "environment": {
                            "SERVER_PORT": str(PORT),
                        },
                    }
                },
            }
        )

        container.add_layer("mock-oauth2-server", layer, combine=True)
        container.autostart()
        self.unit.set_ports(PORT)
        self.unit.status = ActiveStatus()

    def _base_url(self, issuer_id: str) -> str:
        return f"http://{self.app.name}.{self.model.name}.svc.cluster.local:{PORT}/{issuer_id}"

    def _on_get_issuer_info(self, event):
        issuer_id = event.params.get("issuer-id", "default")
        base = self._base_url(issuer_id)
        event.set_results({
            "issuer": base,
            "token-url": f"{base}/token",
            "jwks-url": f"{base}/jwks",
        })

    def _on_get_token(self, event):
        issuer_id = event.params.get("issuer-id", "default")
        client_id = event.params.get("client-id", "test-client")
        client_secret = event.params.get("client-secret", "test-secret")
        scope = event.params.get("scope", "openid")

        token_url = f"{self._base_url(issuer_id)}/token"
        data = f"grant_type=client_credentials&scope={scope}"
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        req = urllib.request.Request(
            token_url,
            data=data.encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())

        event.set_results({"access-token": body["access_token"]})


if __name__ == "__main__":
    main(MockOAuth2Charm)
