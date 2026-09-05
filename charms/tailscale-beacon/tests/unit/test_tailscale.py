# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from credentials import ResolvedCredentials
from tailscale import Tailscale


def test_ensure_snap_uses_shared_snap_library(mocker):
    snap_cache = mocker.patch("tailscale.snap.SnapCache")
    tailscale_snap = snap_cache.return_value.__getitem__.return_value
    Tailscale("beacon/0").ensure_snap("1/stable")
    snap_cache.return_value.__getitem__.assert_called_once_with("tailscale")
    tailscale_snap.ensure.assert_called_once_with(
        mocker.ANY,
        channel="1/stable",
    )


def test_up_passes_backend_key_and_tags(command, tmp_path, monkeypatch):
    monkeypatch.setattr("tailscale.STATE_DIRECTORY", tmp_path)
    monkeypatch.setattr("tailscale.CONNECTED_MARKER", tmp_path / "connected")
    Tailscale("beacon/0").up(
        ResolvedCredentials(
            auth_key="tskey-auth-test",
            login_server="https://headscale.example.com",
            tags=("tag:server", "tag:juju"),
            ephemeral=False,
        )
    )
    assert command.call_args.args[0] == [
        "/snap/bin/tailscale",
        "up",
        "--auth-key=file:/dev/stdin",
        "--login-server=https://headscale.example.com",
        "--reset",
        "--advertise-tags=tag:server,tag:juju",
    ]
    assert command.call_args.kwargs["input"] == "tskey-auth-test"


def test_up_configures_oauth_key_ephemerality(command, tmp_path, monkeypatch):
    monkeypatch.setattr("tailscale.STATE_DIRECTORY", tmp_path)
    monkeypatch.setattr("tailscale.CONNECTED_MARKER", tmp_path / "connected")
    Tailscale("beacon/0").up(
        ResolvedCredentials(
            auth_key="tskey-client-test?preauthorized=true&ephemeral=true",
            login_server="https://controlplane.tailscale.com",
            tags=("tag:server",),
            ephemeral=False,
        )
    )
    assert (
        command.call_args.kwargs["input"]
        == "tskey-client-test?preauthorized=true&ephemeral=false"
    )
    assert "--force-reauth" in command.call_args.args[0]


def test_status_parses_client_json(command):
    command.return_value.stdout = """{
      "BackendState": "Running",
      "Self": {"DNSName": "machine.tailnet.ts.net."},
      "CurrentTailnet": {"Name": "tailnet.ts.net"}
    }"""
    status = Tailscale("beacon/0").status()
    assert status.backend_state == "Running"
    assert status.dns_name == "machine.tailnet.ts.net"
    assert status.tailnet_name == "tailnet.ts.net"


def test_reference_counting(tmp_path, monkeypatch):
    units = tmp_path / "units"
    monkeypatch.setattr("tailscale.UNITS_DIRECTORY", units)
    first = Tailscale("beacon/0")
    second = Tailscale("beacon/1")
    first.register_unit()
    second.register_unit()
    assert first.has_other_units is True
    first.unregister_unit()
    assert second.has_other_units is False
    second.unregister_unit()
    second.unregister_unit()
    assert not any(units.iterdir())


def test_disconnect_only_stops_charm_managed_session(
    tmp_path, monkeypatch, command, mocker
):
    connected = tmp_path / "connected"
    monkeypatch.setattr("tailscale.CONNECTED_MARKER", connected)
    mocker.patch("tailscale.snap.SnapCache")
    tailscale = Tailscale("beacon/0")

    tailscale.disconnect()
    command.assert_not_called()

    connected.touch()
    tailscale.disconnect()
    assert command.call_args.args[0] == ["/snap/bin/tailscale", "down"]
    assert not connected.exists()


def test_configuration_marker_does_not_store_auth_key(
    tmp_path, monkeypatch, command, mocker
):
    configuration = tmp_path / "configuration"
    connected = tmp_path / "connected"
    connected.touch()
    monkeypatch.setattr("tailscale.CONFIGURATION_MARKER", configuration)
    monkeypatch.setattr("tailscale.CONNECTED_MARKER", connected)
    mocker.patch("tailscale.snap.SnapCache")
    credentials = ResolvedCredentials(
        auth_key="tskey-auth-test",
        login_server="https://controlplane.tailscale.com",
        tags=(),
        ephemeral=True,
    )
    tailscale = Tailscale("beacon/0")

    tailscale.mark_configuration_current(credentials, "1/stable")

    assert "tskey-auth-test" not in configuration.read_text()
    assert tailscale.configuration_is_current(credentials, "1/stable")
