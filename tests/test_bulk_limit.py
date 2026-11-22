"""The bulk action accepts a whole queue of episodes, not just 2000 ids."""
import pytest


@pytest.fixture
def signed_in(client, admin_credentials):
    from app.auth.permissions import ALL_PERMISSIONS
    from tests.conftest import do_setup, make_user, session_for
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


def test_a_list_longer_than_2000_ids_is_accepted(client, signed_in):
    ids = [f"job-{i}" for i in range(2500)]
    r = client.post("/api/download/bulk", headers={"X-CSRF-Token": signed_in},
                    json={"action": "pause", "job_ids": ids})
    assert r.status_code == 200
    assert r.json() == {"changed": []}


def test_a_list_above_the_new_limit_is_still_refused(client, signed_in):
    ids = [f"job-{i}" for i in range(10001)]
    r = client.post("/api/download/bulk", headers={"X-CSRF-Token": signed_in},
                    json={"action": "pause", "job_ids": ids})
    assert r.status_code == 422
