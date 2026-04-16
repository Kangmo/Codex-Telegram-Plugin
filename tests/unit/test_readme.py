from pathlib import Path


def test_readme_covers_install_update_service_and_telegram_setup() -> None:
    readme_path = Path(__file__).resolve().parents[2] / "README.md"
    text = readme_path.read_text()

    required_snippets = [
        "curl -fsSL https://raw.githubusercontent.com/Kangmo/Codex-Telegram-Plugin/main/install/install.sh | sh",
        "codex-telegram-gateway configure",
        "codex-telegram-gateway update",
        "codex-telegram-gateway start",
        "codex-telegram-gateway stop",
        "codex-telegram-gateway service install",
        "codex-telegram-gateway service status",
        "@BotFather",
        "Privacy Mode",
        "Topics",
        "group chat ID",
        "numeric user ID",
        "Plugins",
        "Codex Local Plugins",
    ]

    for snippet in required_snippets:
        assert snippet in text
