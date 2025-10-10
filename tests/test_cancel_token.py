"""Kiểm tra hành vi liên kết của CancelToken và ThreadingManager."""

from APP.utils.threading_utils import CancelToken, ThreadingManager


def test_child_token_reflects_parent_cancellation() -> None:
    parent = CancelToken()
    child = parent.derive()

    assert not parent.is_cancelled()
    assert not child.is_cancelled()

    parent.cancel()

    assert parent.is_cancelled()
    assert child.is_cancelled()


def test_child_token_cancellation_does_not_propagate_upwards() -> None:
    parent = CancelToken()
    child = parent.derive()

    assert not parent.is_cancelled()

    child.cancel()

    assert child.is_cancelled()
    assert not parent.is_cancelled()


def test_submit_uses_derived_token_and_respects_parent_cancellation() -> None:
    tm = ThreadingManager(max_workers=1)
    parent = CancelToken()
    observed: dict[str, CancelToken] = {}

    def worker(cancel_token: CancelToken) -> bool:
        observed["token"] = cancel_token
        cancel_token.raise_if_cancelled()
        return cancel_token is parent

    record = tm.submit(
        func=worker,
        group="test",
        name="token-check",
        cancel_token=parent,
    )

    try:
        assert record.token is not parent
        assert record.future.result(timeout=2) is False
        assert observed["token"] is record.token

        parent.cancel()
        assert record.token.is_cancelled()
    finally:
        tm.shutdown(force=True)
