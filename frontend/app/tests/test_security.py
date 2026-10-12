"""Tests for the login rate limiter (password hashing now lives on the backend)."""

from core.security import is_locked, record_attempt


def test_record_attempt_success_unlocks():
    record_attempt('ip-a', success=False)
    record_attempt('ip-a', success=True)
    locked, _ = is_locked('ip-a')
    assert not locked


def test_lockout_after_max_attempts():
    ip = 'ip-b'
    for _ in range(5):
        allowed, _ = record_attempt(ip, success=False)
    allowed, message = record_attempt(ip, success=False)
    assert not allowed
    assert 'locked' in message.lower()
    locked, lock_message = is_locked(ip)
    assert locked


def test_unknown_ip_not_locked():
    locked, _ = is_locked('ip-c')
    assert not locked
