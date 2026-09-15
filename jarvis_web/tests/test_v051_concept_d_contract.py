from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_concept_d_has_required_visual_structure() -> None:
    app = _read("web/src/App.tsx")
    core = _read("web/src/components/JarvisCoreVisual.tsx")
    css = _read("web/src/styles.css")

    for token in (
        "settingsButton",
        "heroCopyLeft",
        "heroCopyRightTop",
        "conversationGlass",
        "suggestionRow",
        "composerUtility",
        "micUtility",
    ):
        assert token in app

    for token in (
        "earthAtmosphere",
        "earthHorizon",
        "orbitThree",
        "orbCorona",
        "orbSpecular",
        "orbParticles",
    ):
        assert token in core

    for label in (
        "Resumir um texto",
        "Ajuda com código",
        "Ideias criativas",
        "Mais opções",
    ):
        assert label in app

    assert ".conversationGlass" in css
    assert ".earthHorizon" in css
    assert ".settingsButton" in css


def test_idle_first_and_delete_active_returns_idle() -> None:
    app = _read("web/src/App.tsx")
    assert "Deliberately do NOT auto-open the newest chat on startup" in app
    assert "Deleting the active chat returns JARVIS to the idle Concept D hero" in app
    assert "setActiveSessionId(null);" in app
    assert "setMessages([]);" in app


def test_game_mode_is_removed_from_frontend() -> None:
    app = _read("web/src/App.tsx")
    api = _read("web/src/api.ts")
    types = _read("web/src/types.ts")
    visual = _read("web/src/components/JarvisCoreVisual.tsx")
    css = _read("web/src/styles.css")

    frontend = "\n".join((app, api, types, visual, css))

    for token in (
        "ConversationMode",
        "GAME_STORAGE_KEY",
        "readGameMode",
        "persistGameMode",
        "toggleGameMode",
        "GameIcon",
        "gameMode",
        "gameToggle",
        "gameActive",
        "jarvis-web-game-mode",
    ):
        assert token not in frontend

    assert "home.control" not in app
    assert "core.control" not in app
    assert "/api/shell" not in app.lower()


def test_test_history_cleanup_is_explicit_not_frontend_hiding() -> None:
    app = _read("web/src/App.tsx")
    sidebar = _read("web/src/components/Sidebar.tsx")
    cleanup = _read("clean-test-history.ps1")
    assert "${jndi" not in app
    assert "${jndi" not in sidebar
    assert "${jndi" in cleanup
    assert "backup-encrypted-history.ps1" in cleanup


def test_delete_backend_contract_still_exists() -> None:
    existing = _read("tests/test_v050_game_delete.py")
    assert "test_delete_chat_is_implemented_and_persistent" in existing
    assert 'client.delete(f"/api/sessions/{session_id}")' in existing
