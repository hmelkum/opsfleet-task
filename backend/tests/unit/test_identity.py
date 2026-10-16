import pytest

from src.core.identity.users import Role, parse_user_id


def test_admin():
    user = parse_user_id("admin")
    assert user.role is Role.ADMIN and user.is_admin


@pytest.mark.parametrize("user_id", ["user_alice", "user_bob.smith", "user_x-1"])
def test_user(user_id):
    user = parse_user_id(user_id)
    assert user.user_id == user_id and user.role is Role.USER and not user.is_admin


@pytest.mark.parametrize("user_id", ["", "alice", "user_", "Admin", "user_a b", "user_" + "a" * 65, "admin2"])
def test_invalid(user_id):
    with pytest.raises(ValueError):
        parse_user_id(user_id)
