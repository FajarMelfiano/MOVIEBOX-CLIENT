import asyncio
import json
from types import SimpleNamespace

from click.testing import CliRunner

from moviebox_api.cli.interface import source_streams_command
from moviebox_api.constants import SubjectType


class _Loop:
    @staticmethod
    def run_until_complete(coroutine):
        return asyncio.run(coroutine)


class _FakeResolver:
    last_provider_name: str | None = None

    def __init__(self, provider_name: str | None = None):
        _FakeResolver.last_provider_name = provider_name

    async def resolve(self, **_kwargs):
        item = SimpleNamespace(
            id="123",
            title="Avatar",
            year=2009,
            page_url="https://example.com/detail/avatar",
            subject_type=SubjectType.MOVIES,
        )
        return item, [], []


def test_source_streams_accepts_dynamic_provider_syntax(monkeypatch):
    monkeypatch.setattr("moviebox_api.cli.interface.SourceResolver", _FakeResolver)
    monkeypatch.setattr("moviebox_api.cli.interface.get_event_loop", lambda: _Loop())

    runner = CliRunner()
    result = runner.invoke(
        source_streams_command,
        ["Avatar", "--provider", "vega:autoEmbed", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["provider"] == "vega:autoEmbed"
    assert _FakeResolver.last_provider_name == "vega:autoEmbed"


def test_source_streams_supports_legacy_vega_option(monkeypatch):
    monkeypatch.setattr("moviebox_api.cli.interface.SourceResolver", _FakeResolver)
    monkeypatch.setattr("moviebox_api.cli.interface.get_event_loop", lambda: _Loop())

    runner = CliRunner()
    result = runner.invoke(
        source_streams_command,
        ["Avatar", "--provider", "vega", "--vega-provider", "autoEmbed", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["provider"] == "vega:autoEmbed"
    assert _FakeResolver.last_provider_name == "vega:autoEmbed"


def test_source_streams_rejects_unsupported_provider():
    runner = CliRunner()
    result = runner.invoke(source_streams_command, ["Avatar", "--provider", "not-a-provider"])

    assert result.exit_code > 0
    assert "Unsupported provider" in result.output
