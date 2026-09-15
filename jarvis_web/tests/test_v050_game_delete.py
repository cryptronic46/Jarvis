from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_removed_mode_field_is_rejected() -> None:
    for mode in (
        "game",
        "standard",
        "root",
    ):
        app, client = make_authenticated_client()

        try:
            response = client.post(
                "/api/chat",
                json={
                    "message": "Ol?",
                    "mode": mode,
                },
            )

            assert response.status_code == 422

        finally:
            client.__exit__(
                None,
                None,
                None,
            )


def test_delete_chat_is_implemented_and_persistent() -> None:
    app, client = make_authenticated_client()

    try:
        created = client.post(
            "/api/sessions"
        )

        assert created.status_code == 201

        session_id = created.json()["id"]

        deleted = client.delete(f"/api/sessions/{session_id}")

        assert deleted.status_code == 204

        missing = client.get(
            f"/api/sessions/{session_id}"
        )

        assert missing.status_code == 404

        ids = {
            item["id"]
            for item in client.get(
                "/api/sessions"
            ).json()
        }

        assert session_id not in ids

    finally:
        client.__exit__(
            None,
            None,
            None,
        )
