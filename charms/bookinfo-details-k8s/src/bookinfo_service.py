"""Simplified library for Bookinfo service communication.

This library provides a minimal interface for Bookinfo services to communicate
with each other through Juju relations.
"""

import logging
from typing import Optional

from ops.charm import CharmBase
from ops.framework import EventBase, EventSource, Object, ObjectEvents

logger = logging.getLogger(__name__)


class BookinfoServiceProvider(Object):
    """Provider side of a Bookinfo service relation."""

    def __init__(self, charm: CharmBase, relation_name: str, port: int):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._port = port

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)

    def _on_relation_joined(self, event):
        """Handle relation joined."""
        self._update_relation_data(event.relation)

    def _on_relation_changed(self, event):
        """Handle relation changed."""
        self._update_relation_data(event.relation)

    def _update_relation_data(self, relation):
        """Update relation data with service URL."""
        if not self._charm.unit.is_leader():
            return

        # Use socket.getfqdn() to get the FQDN
        # fqdn = socket.getfqdn()
        url = f"http://{self._charm.app.name}:{self._port}"

        relation.data[self._charm.app]["url"] = url
        logger.info(f"Published URL: {url}")


class ServiceUrlChangedEvent(EventBase):
    """Event emitted when service URL changes."""

    def __init__(self, handle, url: Optional[str]):
        super().__init__(handle)
        self.url = url

    def snapshot(self):
        """Save event data for persistence across hook executions."""
        return {"url": self.url}

    def restore(self, snapshot):
        """Restore event data from snapshot."""
        self.url = snapshot["url"]


class BookinfoServiceConsumerEvents(ObjectEvents):
    """Events for Bookinfo service consumer."""

    url_changed = EventSource(ServiceUrlChangedEvent)


class BookinfoServiceConsumer(Object):
    """Consumer side of a Bookinfo service relation."""

    on = BookinfoServiceConsumerEvents()  # pyright: ignore

    def __init__(self, charm: CharmBase, relation_name: str):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_joined(self, event):
        """Handle relation joined."""
        logger.info(f"Joined {self._relation_name} relation")

    def _on_relation_changed(self, event):
        """Handle relation changed."""
        if not event.app:
            return

        data = event.relation.data[event.app]
        url = data.get("url")

        if url:
            logger.info(f"Received URL from {event.app.name}: {url}")
            self.on.url_changed.emit(url)

    def _on_relation_broken(self, event):
        """Handle relation broken."""
        logger.info(f"Broken {self._relation_name} relation")
        self.on.url_changed.emit(None)
