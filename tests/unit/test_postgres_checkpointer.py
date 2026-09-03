from contextlib import contextmanager
from unittest.mock import MagicMock, patch


def test_mask_database_url_redacts_credentials_and_password_query():
    from backend.checkpoint.postgres_checkpointer import mask_database_url

    masked = mask_database_url(
        "postgresql://researchflow:secret@localhost:5432/researchflow?password=also-secret&sslmode=require"
    )

    assert "secret" not in masked
    assert "also-secret" not in masked
    assert "researchflow:[REDACTED]@localhost:5432/researchflow" in masked
    assert "sslmode=require" in masked


def test_get_checkpoint_database_url_converts_asyncpg_without_rewriting_host(monkeypatch):
    from backend.checkpoint import postgres_checkpointer as module

    monkeypatch.setattr(
        module.settings,
        "POSTGRES_URL",
        "postgresql+asyncpg://user:password@127.0.0.1:5433/researchflow",
    )

    assert (
        module.get_checkpoint_database_url()
        == "postgresql://user:password@127.0.0.1:5433/researchflow"
    )


def test_build_graph_config_stringifies_run_id():
    from backend.checkpoint.postgres_checkpointer import build_graph_config

    assert build_graph_config(42) == {"configurable": {"thread_id": "42"}}


def test_setup_uses_postgres_saver_context_and_calls_setup():
    from backend.checkpoint import postgres_checkpointer as module

    saver = MagicMock()

    @contextmanager
    def fake_from_conn_string(url):
        assert url == "postgresql://user:password@localhost:5432/test"
        yield saver

    with patch.object(module.settings, "POSTGRES_URL", "postgresql+asyncpg://user:password@localhost:5432/test"), \
         patch.object(module.PostgresSaver, "from_conn_string", side_effect=fake_from_conn_string):
        module.setup_postgres_checkpointer()

    saver.setup.assert_called_once_with()


def test_get_postgres_checkpointer_keeps_context_open_until_reset():
    from backend.checkpoint import postgres_checkpointer as module

    saver = MagicMock()
    state = {"entered": False, "closed": False}

    class FakeContext:
        def __enter__(self):
            state["entered"] = True
            return saver

        def __exit__(self, exc_type, exc_value, traceback):
            state["closed"] = True
            return False

    module.reset_postgres_checkpointer()
    with patch.object(module.PostgresSaver, "from_conn_string", return_value=FakeContext()):
        result = module.get_postgres_checkpointer()
        assert result is saver
        assert state["entered"]
        assert not state["closed"]
        assert module.get_postgres_checkpointer() is saver

    module.reset_postgres_checkpointer()
    assert state["closed"]
