from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frontend_launches_idle_without_auto_opening_latest_chat() -> None:
    source = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "Deliberately do NOT auto-open the newest chat on startup" in source
    assert "await loadSession(list[0].id)" not in source


def test_frontend_has_animated_core_without_game_mode() -> None:
    app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    api = (ROOT / "web" / "src" / "api.ts").read_text(encoding="utf-8")
    types = (ROOT / "web" / "src" / "types.ts").read_text(encoding="utf-8")
    visual = (ROOT / "web" / "src" / "components" / "JarvisCoreVisual.tsx").read_text(encoding="utf-8")
    css = (ROOT / "web" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "JarvisCoreVisual" in app
    assert "jarvisOrb" in visual
    assert "prefers-reduced-motion" in css

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


def test_frontend_delete_requires_confirmation_modal() -> None:
    app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    sidebar = (ROOT / "web" / "src" / "components" / "Sidebar.tsx").read_text(encoding="utf-8")
    assert "Eliminar esta conversa?" in app
    assert "onRequestDelete" in sidebar


def test_frontend_has_no_privileged_permission_code() -> None:
    app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
    assert "home.control" not in app
    assert "core.control" not in app
    assert "security.manage_local" not in app
