"""The Claude client can be made on a machine whose certificate settings point at nothing.

None of these tests sends a request: making the client does not contact Claude.
"""

import os

from app.llm import ClaudeLLM, forget_missing_certificates


def test_a_certificate_file_that_is_not_there_is_ignored(monkeypatch, tmp_path):
    """Conda in Git Bash on Windows sets SSL_CERT_FILE to a path that does not exist, and the
    HTTP library then fails before any request is made."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ssl" / "cacert.pem"))
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert ClaudeLLM(api_key="not-a-real-key").client is not None
    assert "SSL_CERT_FILE" not in os.environ


def test_a_certificate_folder_that_is_not_there_is_ignored(monkeypatch, tmp_path):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "certs"))
    assert forget_missing_certificates() == ["SSL_CERT_DIR"]
    assert "SSL_CERT_DIR" not in os.environ


def test_certificate_settings_that_point_at_something_are_kept(monkeypatch, tmp_path):
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    assert forget_missing_certificates() == []
    assert os.environ["SSL_CERT_FILE"] == str(bundle)
    assert os.environ["SSL_CERT_DIR"] == str(tmp_path)
