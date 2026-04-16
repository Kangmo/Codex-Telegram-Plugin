from types import SimpleNamespace

from codex_telegram_gateway import cli


def test_update_command_reports_origin_and_install_root(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def _fake_update(paths):
        return SimpleNamespace(
            origin_url="https://github.com/Kangmo/Codex-Telegram-Plugin",
            install_root=paths.install_root,
        )

    monkeypatch.setattr("codex_telegram_gateway.cli.perform_self_update", _fake_update)

    cli.main(["update"])

    assert capsys.readouterr().out == (
        "Updated plugin source from https://github.com/Kangmo/Codex-Telegram-Plugin\n"
        + f"Install root: {tmp_path / '.codex-telegram-plugin'}\n"
    )
