from fastapi.testclient import TestClient

from jarvis_web.backend.app import create_app


TEST_BOOTSTRAP_TOKEN = "test-bootstrap-token-0123456789-abcdef"


def make_authenticated_client(*, dev_mode: bool = False):
    app = create_app(
        dev_mode=dev_mode,
        bootstrap_token=TEST_BOOTSTRAP_TOKEN,
    )
    client = TestClient(app)
    client.__enter__()

    response = client.get(
        "/auth/bootstrap",
        params={"token": TEST_BOOTSTRAP_TOKEN},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return app, client
