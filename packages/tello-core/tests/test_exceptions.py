"""Tests for tello_core exception hierarchy."""

from tello_core.exceptions import (
    TelloError,
    ConfigurationError,
    ConnectionError as TelloConnectionError,
    CommandError,
    ValidationError as TelloValidationError,
)


def test_tello_error_is_base_exception():
    err = TelloError("base error")
    assert isinstance(err, Exception)
    assert str(err) == "base error"


def test_configuration_error_inherits_tello_error():
    err = ConfigurationError("bad config")
    assert isinstance(err, TelloError)


def test_connection_error_inherits_tello_error():
    err = TelloConnectionError("no connection")
    assert isinstance(err, TelloError)


def test_command_error_inherits_tello_error():
    err = CommandError("command failed")
    assert isinstance(err, TelloError)


def test_validation_error_inherits_tello_error():
    err = TelloValidationError("invalid input")
    assert isinstance(err, TelloError)


def test_all_exceptions_are_distinct():
    """Each exception type should be catchable independently."""
    with_config = ConfigurationError("x")
    with_conn = TelloConnectionError("x")
    with_cmd = CommandError("x")
    with_val = TelloValidationError("x")

    assert type(with_config) is not type(with_conn)
    assert type(with_conn) is not type(with_cmd)
    assert type(with_cmd) is not type(with_val)
