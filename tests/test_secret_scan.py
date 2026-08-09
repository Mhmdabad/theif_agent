"""Unit tests for the secret scanner gate (``scripts/secret_scan.py``).

Every fake credential below is assembled by string concatenation at runtime so
that this file, which the scanner itself scans, never contains a matching
string at rest.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "secret_scan.py"


def load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("secret_scan", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def findings_for(tmp_path: Path, name: str, text: str) -> list[str]:
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    result = load_scanner().content_findings(target)
    assert isinstance(result, list)
    return result


def test_forbidden_filenames_flagged() -> None:
    scanner = load_scanner()
    for name in (
        "credentials.json",
        "token_cache.json",
        "client_secret_x.json",
        "server.pem",
        "id_rsa.key",
        ".env",
        "prod.env",
        "secrets.yaml",
    ):
        assert scanner.name_findings(Path(name)), name


def test_ordinary_filenames_pass() -> None:
    scanner = load_scanner()
    for name in ("main.py", "README.md", "config.json", "keyring_notes.md"):
        assert scanner.name_findings(Path(name)) == [], name


def test_gocspx_token_caught(tmp_path: Path) -> None:
    leaked = "GOCSPX-" + "x" * 20
    found = findings_for(tmp_path, "leak.txt", f"secret is {leaked}\n")
    assert len(found) == 1
    assert "GOCSPX" in found[0]
    assert found[0].endswith(":1: Google OAuth client secret (GOCSPX token)")


def test_high_signal_patterns_caught(tmp_path: Path) -> None:
    aws = "AKIA" + "A" * 16
    bearer = "ya29" + "." + "a" * 25
    pem = "-----BEGIN " + "PRIVATE KEY-----"
    ngrok = "authtoken " + "a" * 20 + "_" + "b" * 20
    body = "\n".join((aws, bearer, pem, ngrok)) + "\n"
    found = findings_for(tmp_path, "leak.txt", body)
    assert len(found) == 4


def test_hardcoded_password_caught_but_placeholder_allowed(tmp_path: Path) -> None:
    live = "password = " + '"' + "hunter2hunter2" + '"'
    assert len(findings_for(tmp_path, "live.py", live + "\n")) == 1
    fake = "password = " + '"' + "example-not-a-real-value" + '"'
    assert findings_for(tmp_path, "fake.py", fake + "\n") == []


def test_prose_and_binary_pass(tmp_path: Path) -> None:
    prose = "Never commit client_secret files; rotate any GOCSPX- prefixed value.\n"
    assert findings_for(tmp_path, "notes.md", prose) == []
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01" + b"GOCSPX-" + b"x" * 20)
    assert load_scanner().content_findings(binary) == []


def test_repo_is_clean() -> None:
    assert load_scanner().main() == 0
