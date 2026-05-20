from interlock.align.embed import embed_voyage


def test_embed_voyage_uses_voyage_client(mocker) -> None:  # type: ignore[no-untyped-def]
    fake_response = mocker.Mock()
    fake_response.embeddings = [[0.1, 0.2], [0.3, 0.4]]
    fake_client = mocker.Mock()
    fake_client.embed.return_value = fake_response
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    vecs = embed_voyage(["Impedance", "Z"])
    assert set(vecs.keys()) == {"Impedance", "Z"}
    assert vecs["Impedance"] == [0.1, 0.2]
    assert vecs["Z"] == [0.3, 0.4]
    fake_client.embed.assert_called_once()


def test_embed_voyage_propagates_error(mocker) -> None:  # type: ignore[no-untyped-def]
    fake_client = mocker.Mock()
    fake_client.embed.side_effect = RuntimeError("rate limit")
    mocker.patch("interlock.align.embed.voyageai.Client", return_value=fake_client)
    mocker.patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"})

    try:
        embed_voyage(["x"])
    except RuntimeError as e:
        assert "rate limit" in str(e)
        return
    raise AssertionError("RuntimeError should propagate")
