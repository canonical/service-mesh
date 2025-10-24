"""Step definitions for authorization policies tests."""

import logging

from pytest_bdd import then

from tests.integration.helpers import verify_http_response

logger = logging.getLogger(__name__)


# -------------- Then --------------


@then("the request is forbidden")
def request_is_forbidden(juju_run_output: dict):
    """Verify the last request was forbidden with HTTP 403."""
    result = juju_run_output.get("last_request")
    assert result is not None, "No request result found"

    verify_http_response(result, expected_http_code=403, expected_exit_code=0)
