import pytest

from interlock.align.embed import embed_voyage
from interlock.cache.disk import clear_namespace


@pytest.fixture(autouse=True)
def _isolate_voyage_cache() -> None:  # type: ignore[misc]
    """Each embed test starts with an empty Voyage cache so mocks aren't
    short-circuited by cached vectors from a previous test."""
    clear_namespace("voyage-embeddings")
    yield
    clear_namespace("voyage-embeddings")


def test_embed_voyage_uses_voyage_client(mocker) -> None:  # type: ignore[no-untyped-def]
    fake_response = mocker.Mock()
    fake_response.embeddings = [[0.1, 0.2], [0.3, 0.4]]
    fake_client = mocker.Mock()
    fake_client.embed.return_value = fake_response
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    vecs = embed_voyage(["TestNameAlpha", "TestNameBeta"])
    assert set(vecs.keys()) == {"TestNameAlpha", "TestNameBeta"}
    assert vecs["TestNameAlpha"] == [0.1, 0.2]
    assert vecs["TestNameBeta"] == [0.3, 0.4]
    # Single batched call for both uncached texts.
    fake_client.embed.assert_called_once()


def test_embed_voyage_caches_per_text(mocker) -> None:  # type: ignore[no-untyped-def]
    """Second invocation with the same text must hit cache (no API call)."""
    fake_response = mocker.Mock()
    fake_response.embeddings = [[0.5, 0.6]]
    fake_client = mocker.Mock()
    fake_client.embed.return_value = fake_response
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    first = embed_voyage(["CachedTestName"])
    second = embed_voyage(["CachedTestName"])
    assert first == second
    assert fake_client.embed.call_count == 1, "second call must hit cache"


def test_embed_voyage_mixes_cached_and_uncached(mocker) -> None:  # type: ignore[no-untyped-def]
    """First call populates cache for one text; second call should only
    invoke the API for the new uncached text."""
    # First call: only known text
    r1 = mocker.Mock()
    r1.embeddings = [[1.0, 0.0]]
    # Second call: only new text
    r2 = mocker.Mock()
    r2.embeddings = [[0.0, 1.0]]
    fake_client = mocker.Mock()
    fake_client.embed.side_effect = [r1, r2]
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    embed_voyage(["AlreadyCached"])
    vecs = embed_voyage(["AlreadyCached", "FreshlyAdded"])
    assert vecs["AlreadyCached"] == [1.0, 0.0]
    assert vecs["FreshlyAdded"] == [0.0, 1.0]
    # Second batch should only request the new text.
    second_call_args = fake_client.embed.call_args_list[1]
    requested = second_call_args[0][0]
    assert requested == ["FreshlyAdded"], (
        f"second call should batch only the uncached text, got {requested}"
    )


def test_embed_voyage_propagates_error(mocker) -> None:  # type: ignore[no-untyped-def]
    fake_client = mocker.Mock()
    fake_client.embed.side_effect = RuntimeError("rate limit")
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    try:
        embed_voyage(["FreshUncachedText"])
    except RuntimeError as e:
        assert "rate limit" in str(e)
        return
    raise AssertionError("RuntimeError should propagate")
