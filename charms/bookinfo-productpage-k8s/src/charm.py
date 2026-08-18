#!/usr/bin/env python3
"""Charm for the Product Page microservice."""

import logging
import socket
from typing import Dict, Optional
from urllib.parse import urlparse

from charmlibs.interfaces.istio_request_auth import (
    ClaimToHeader,
    IstioRequestAuthRequirer,
    JWTRule,
)
from charms.istio_beacon_k8s.v0.service_mesh import (
    AppPolicy,
    Endpoint,
    Method,
    ServiceMeshConsumer,
)
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import LayerDict

from bookinfo_service import BookinfoServiceConsumer

logger = logging.getLogger(__name__)


class ProductPageK8sCharm(CharmBase):
    """Charm for the Product Page microservice."""

    _stored = StoredState()

    # WSGI wrapper template for handling path prefixes
    WRAPPER_TEMPLATE = '''#!/usr/bin/env python3
import re
from productpage import app as original_app

# Path prefix from ingress
PREFIX = "{prefix}"

class PathPrefixMiddleware:
    """Middleware to handle path prefixes for hardcoded URLs."""

    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        # Buffer to capture response details
        response_data = []

        def custom_start_response(status, headers, exc_info=None):
            response_data.append((status, headers))
            return start_response(status, headers, exc_info)

        # Get response from app
        app_iter = self.app(environ, custom_start_response)

        # Check if this is an HTML response
        if response_data:
            headers = dict(response_data[0][1])
            content_type = headers.get('Content-Type', '')

            # Only process HTML responses
            if 'text/html' in content_type:
                return self._fix_paths(app_iter)

        return app_iter

    def _fix_paths(self, app_iter):
        """Fix hardcoded paths in HTML responses."""
        try:
            # Collect response body
            response_body = b''.join(app_iter)

            # Convert to string for processing
            body_str = response_body.decode('utf-8')

            # Fix hardcoded paths
            # Replace href="/logout" with href="{prefix}/logout"
            body_str = re.sub(r'href="/logout"', f'href="{{self.prefix}}/logout"', body_str)

            # Replace action="login" with absolute path including prefix
            body_str = re.sub(r'action="login"', f'action="{{self.prefix}}/login"', body_str)

            # Replace /static/ paths
            body_str = re.sub(r'(src|href)="/static/', r'\\1="' + self.prefix + '/static/', body_str)

            # Return modified response
            yield body_str.encode('utf-8')
        finally:
            # Close original iterator
            if hasattr(app_iter, 'close'):
                app_iter.close()

# Apply middleware if prefix exists
if PREFIX:
    app = PathPrefixMiddleware(original_app, PREFIX)
else:
    app = original_app
'''

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(pebble_ready=False)

        self.container = self.unit.get_container("bookinfo-productpage")

        # Core event handlers
        self.framework.observe(self.on.bookinfo_productpage_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        # Ingress setup
        self._ingress = IngressPerAppRequirer(
            charm=self,
            port=int(self.config["port"]),
            strip_prefix=True,
            redirect_https=True,
            scheme="http",
        )
        self.framework.observe(self._ingress.on.ready, self._on_ingress_ready)

        # Service consumers
        self._details_consumer = BookinfoServiceConsumer(self, "details")
        self.framework.observe(self._details_consumer.on.url_changed, self._on_relation_changed)

        self._reviews_consumer = BookinfoServiceConsumer(self, "reviews")
        self.framework.observe(self._reviews_consumer.on.url_changed, self._on_relation_changed)

        self._ratings_consumer = BookinfoServiceConsumer(self, "ratings")
        self.framework.observe(self._ratings_consumer.on.url_changed, self._on_relation_changed)

        # Service mesh with authorization policies
        self._mesh = ServiceMeshConsumer(
            self,
            policies=[
                AppPolicy(
                    relation="website",
                    endpoints=[
                        Endpoint(
                            ports=[int(self.config["port"])],
                            methods=[Method.get],
                            paths=["/productpage", "/static/*", "/login", "/logout", "/health"],
                        )
                    ],
                )
            ],
        )

        # Actions
        self.framework.observe(self.on.get_url_action, self._get_url)

        # Request authentication (JWT rules for Istio ingress)
        self._request_auth = IstioRequestAuthRequirer(self, relation_name="istio-request-auth")
        self.framework.observe(
            self.on["istio-request-auth"].relation_joined, self._on_request_auth_joined
        )

        # Initial port configuration
        self._set_ports()

    def _on_pebble_ready(self, event):
        """Handle the pebble ready event."""
        self._stored.pebble_ready = True
        self._reconcile()

    def _on_config_changed(self, event):
        """Handle config changed event."""
        self._publish_request_auth()
        self._reconcile()

    def _on_update_status(self, event):
        """Handle update status event."""
        self._reconcile()

    def _on_ingress_ready(self, event):
        """Handle ingress ready event."""
        self._reconcile()

    def _on_relation_changed(self, event):
        """Handle any relation changed event."""
        self._reconcile()

    def _on_request_auth_joined(self, _):
        """Publish JWT rules when the request-auth relation is established."""
        self._publish_request_auth()

    def _publish_request_auth(self):
        """Publish JWT rules if the relation exists and config is set."""
        relations = self.model.relations.get("istio-request-auth")
        if not relations:
            logger.info("request-auth: no relation, skipping")
            return

        issuer = str(self.config.get("jwt-issuer", ""))
        jwks_uri = str(self.config.get("jwt-jwks-uri", ""))
        if not issuer or not jwks_uri:
            logger.info("request-auth: missing config (issuer=%r, jwks_uri=%r)", issuer, jwks_uri)
            return

        logger.info("request-auth: publishing JWT rules (issuer=%s)", issuer)
        self._request_auth.publish_data(
            [
                JWTRule(
                    issuer=issuer,
                    jwks_uri=jwks_uri,
                    forward_original_token=True,
                    claim_to_headers=[
                        ClaimToHeader(header="x-jwt-email", claim="email"),
                        ClaimToHeader(header="x-jwt-sub", claim="sub"),
                    ],
                )
            ]
        )

    def _reconcile(self):
        """Reconcile the charm state.

        This is the main reconciliation loop that ensures the charm
        converges to the desired state regardless of which event triggered it.
        """
        # Update status first
        if not self._stored.pebble_ready:
            self.unit.status = WaitingStatus("Waiting for pebble ready")
            return

        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Waiting for container")
            return

        # Get current state from relations
        available_services = self._get_available_services()

        # Check if we have minimum required services
        if not available_services:
            self.unit.status = WaitingStatus("Waiting for at least 1 backend service relation")
            return

        # Update configuration
        try:
            self._update_layer()
            self._set_ports()

            # Check if service is running
            service = self.container.get_service("productpage")
            if service.is_running():
                self.unit.status = ActiveStatus(
                    f"Ready with {len(available_services)} backend services"
                )
            else:
                self.unit.status = MaintenanceStatus("Service not running")
        except Exception as e:
            logger.error(f"Failed to reconcile: {e}")
            self.unit.status = BlockedStatus(f"Failed to reconcile: {str(e)}")

    def _get_available_services(self) -> list:
        """Get list of available backend services."""
        services = []
        if self._get_service_url("details"):
            services.append("details")
        if self._get_service_url("reviews"):
            services.append("reviews")
        if self._get_service_url("ratings"):
            services.append("ratings")
        return services

    def _get_service_url(self, service_name: str) -> Optional[str]:
        """Get a service URL directly from relation data."""
        try:
            # Get the first relation for this service (typically only one)
            relations = self.model.relations.get(service_name, [])
            if relations:
                relation = relations[0]  # Take the first relation
                return relation.data[relation.app].get("url")
        except Exception as e:
            logger.warning(f"Failed to get {service_name} URL: {e}")
        return None

    def _update_layer(self):
        """Update the Pebble layer configuration."""
        if not self.container.can_connect():
            logger.debug("Cannot connect to container")
            return

        # Create wrapper to handle path prefix if we have an ingress
        if self._ingress.url:
            self._create_wsgi_wrapper()

        layer = self._generate_layer()
        self.container.add_layer("productpage", layer, combine=True)

        try:
            self.container.replan()
            logger.info("Service layer updated")
        except Exception as e:
            logger.error(f"Failed to replan service: {e}")
            raise

    def _create_wsgi_wrapper(self):
        """Create a WSGI wrapper that fixes hardcoded URLs for path prefix support."""
        # Get the path prefix from ingress URL
        prefix = ""
        if ingress_url := self._ingress.url:
            parsed = urlparse(ingress_url)
            if parsed.path and parsed.path != "/":
                prefix = parsed.path.rstrip("/")

        # Generate wrapper content from template
        wrapper_content = self.WRAPPER_TEMPLATE.format(prefix=prefix)

        try:
            self.container.push(
                "/opt/microservices/productpage_wrapper.py", wrapper_content, make_dirs=True
            )
            logger.info(f"Created WSGI wrapper with prefix: {prefix}")
        except Exception as e:
            logger.error(f"Failed to create wrapper: {e}")

    def _generate_layer(self) -> LayerDict:
        """Generate the Pebble layer configuration."""
        # Use wrapper if we have ingress (to handle path prefix)
        app_module = "productpage_wrapper:app" if self._ingress.url else "productpage:app"
        return {
            "summary": "Product Page service layer",
            "description": "Pebble layer for the Product Page microservice",
            "services": {
                "productpage": {
                    "override": "replace",
                    "summary": "Product Page service",
                    "command": f"gunicorn -b \"[::]\":{self.config['port']} {app_module} -w 8 --keep-alive 2 -k gevent --forwarded-allow-ips='*'",
                    "startup": "enabled",
                    "environment": self._get_environment(),
                }
            },
        }

    def _get_environment(self) -> Dict[str, str]:
        """Get environment variables for the service."""
        env = {
            "SERVICE_NAME": "productpage",
            "SERVICE_VERSION": "v1",
            # Experimental: log level may not actually affect the service logging
            "LOG_LEVEL": self.config["log-level"],
            "FLOOD_FACTOR": str(self.config["flood-factor"]),
        }

        # Extract hostname and port from URLs for upstream compatibility
        details_url = self._get_service_url("details")
        if details_url:
            parsed = urlparse(details_url)
            env["DETAILS_HOSTNAME"] = parsed.hostname or "details"
            env["DETAILS_SERVICE_PORT"] = str(parsed.port or 9080)

        reviews_url = self._get_service_url("reviews")
        if reviews_url:
            parsed = urlparse(reviews_url)
            env["REVIEWS_HOSTNAME"] = parsed.hostname or "reviews"
            env["REVIEWS_SERVICE_PORT"] = str(parsed.port or 9080)

        ratings_url = self._get_service_url("ratings")
        if ratings_url:
            parsed = urlparse(ratings_url)
            env["RATINGS_HOSTNAME"] = parsed.hostname or "ratings"
            env["RATINGS_SERVICE_PORT"] = str(parsed.port or 9080)

        return env

    def _set_ports(self):
        """Open the application ports to fix Juju's 65535 placeholder issue."""
        try:
            port = int(self.config["port"])
            self.unit.open_port("tcp", port)
            logger.info(f"Opened TCP port {port}")
        except Exception as e:
            logger.warning(f"Failed to open port: {e}")

    def _get_url(self, event: ActionEvent):
        """Return the external hostname to be passed to ingress via the relation.

        If we do not have an ingress, then use the pod dns name as hostname.
        Relying on cluster's DNS service, those dns names are routable virtually
        exclusively inside the cluster.
        """
        output = self._internal_url
        if ingress_url := self._ingress.url:
            output = ingress_url
        if not output.endswith("/"):
            output = output + "/"
        # NOTE: just give the user the product page url instead of the overview since redirect isn't working right.
        output = output + "productpage?u=normal"
        event.set_results({"url": output})

    @property
    def _internal_url(self) -> str:
        """Return the fqdn dns-based in-cluster (private) address of the catalogue server."""
        scheme = "http"
        port = int(self.config["port"])
        return f"{scheme}://{socket.getfqdn()}:{port}"


if __name__ == "__main__":
    main(ProductPageK8sCharm)
