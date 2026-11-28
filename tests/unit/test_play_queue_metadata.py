import sys
from unittest.mock import MagicMock

# Prior test modules (test_adapter_stopped_state.py, test_audio_settings.py)
# stub heavy transitive deps - including dotmap, xmltodict, settings, plex.*
# and dlna.* - as bare MagicMock modules and never restore them. Only purge
# entries that actually look like a leftover stub, so a legitimately real
# module already imported elsewhere (e.g. plex.adapters, loaded for real by
# test_adapter_stopped_state.py against the real "plex" package path) is left
# alone rather than needlessly reimported (consistent with
# test_audio_settings.py / test_xml_unescape.py).
for _key in list(sys.modules):
    if not (_key in ("utils", "plex", "dotmap", "xmltodict", "settings")
            or _key.startswith(("utils.", "plex.", "dotmap.", "xmltodict.", "settings."))):
        continue
    _mod = sys.modules[_key]
    if isinstance(_mod, MagicMock) or (
        hasattr(_mod, "__file__") and _mod.__file__ and "<stub" in str(_mod.__file__)
    ):
        del sys.modules[_key]

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from dotmap import DotMap
import plex.play_queue as play_queue_mod
from plex.play_queue import PlayQueue


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    """Ensure play_queue.settings is not a leftover MagicMock from another test file."""
    monkeypatch.setattr(play_queue_mod, "settings", SimpleNamespace(pms_address=None))


def _make_queue(plex_lib=None):
    return PlayQueue(container_key="/playQueues/1", plex_lib=plex_lib)


def _make_plex_lib(protocol="http", address="192.168.1.50", port="32400", token="secret-token"):
    lib = SimpleNamespace(protocol=protocol, address=address, port=port, token=token)

    def build_url(resource: str, token: bool = True) -> str:
        if play_queue_mod.settings.pms_address:
            url = f"http://{play_queue_mod.settings.pms_address}:{lib.port}{resource}"
        else:
            url = f"{lib.protocol}://{lib.address}:{lib.port}{resource}"
        if token:
            sep = "&" if "?" in resource else "?"
            url += f"{sep}X-Plex-Token={lib.token}"
        return url

    lib.build_url = build_url
    return lib


def _track(**overrides):
    data = {
        "ratingKey": "999",
        "title": "My Song",
        "grandparentTitle": "My Artist",
        "parentTitle": "My Album",
        "duration": 180000,
        "Media": [{"container": "flac", "Part": [{"container": "flac", "key": "/x"}]}],
    }
    data.update(overrides)
    return DotMap(data)


def test_metadata_for_direct_play_track_uses_container_mime_type():
    queue = _make_queue()
    track = _track()
    metadata = queue.metadata_for_track(track, "http://host/stream.flac", force_transcode=False)
    assert 'protocolInfo="http-get:*:audio/flac:*"' in metadata
    assert "<dc:title>My Song</dc:title>" in metadata
    assert "<upnp:artist>My Artist</upnp:artist>" in metadata
    assert "<upnp:album>My Album</upnp:album>" in metadata


def test_metadata_for_transcoded_track_always_uses_mpeg():
    """Transcoded tracks are always served as audio/mpeg by Plex's universal
    transcode endpoint (see build_transcode_url), regardless of the source
    container - metadata must reflect the actual bytes on the wire, not the
    original file format."""
    queue = _make_queue()
    track = _track()  # source is flac
    metadata = queue.metadata_for_track(track, "http://host/transcode.mp3", force_transcode=True)
    assert 'protocolInfo="http-get:*:audio/mpeg:*"' in metadata


def test_metadata_for_track_missing_title_has_fallback():
    queue = _make_queue()
    track = _track(title=None)
    metadata = queue.metadata_for_track(track, "http://host/stream.mp3", force_transcode=False)
    assert "<dc:title>Unknown Title</dc:title>" in metadata


def test_metadata_for_track_is_never_empty():
    """Core regression for issue #10: CurrentURIMetaData must never come
    back as an empty/falsy string, which is what triggered Samsung's
    SetAVTransportURI SOAP Fault rejection."""
    queue = _make_queue()
    track = _track()
    metadata = queue.metadata_for_track(track, "http://host/stream.mp3", force_transcode=False)
    assert metadata
    assert metadata.strip() != ""


def _extract_album_art_uri(metadata: str) -> str | None:
    root = ET.fromstring(metadata)
    ns = {"upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/"}
    el = root.find(".//upnp:albumArtURI", ns)
    return el.text if el is not None else None


def test_metadata_album_art_priority_order():
    queue = _make_queue(plex_lib=_make_plex_lib())

    # 1. thumb takes precedence over all others
    track = _track(
        thumb="/library/metadata/1/thumb/10",
        parentThumb="/library/metadata/2/thumb/20",
        grandparentThumb="/library/metadata/3/thumb/30",
        art="/library/metadata/3/art/40",
    )
    assert _extract_album_art_uri(queue.metadata_for_track(track, "http://host/s.flac")) == (
        "http://192.168.1.50:32400/library/metadata/1/thumb/10?X-Plex-Token=secret-token"
    )

    # 2. parentThumb when thumb is absent
    track = _track(
        parentThumb="/library/metadata/2/thumb/20",
        grandparentThumb="/library/metadata/3/thumb/30",
        art="/library/metadata/3/art/40",
    )
    assert _extract_album_art_uri(queue.metadata_for_track(track, "http://host/s.flac")) == (
        "http://192.168.1.50:32400/library/metadata/2/thumb/20?X-Plex-Token=secret-token"
    )

    # 3. grandparentThumb when thumb and parentThumb are absent
    track = _track(
        grandparentThumb="/library/metadata/3/thumb/30",
        art="/library/metadata/3/art/40",
    )
    assert _extract_album_art_uri(queue.metadata_for_track(track, "http://host/s.flac")) == (
        "http://192.168.1.50:32400/library/metadata/3/thumb/30?X-Plex-Token=secret-token"
    )

    # 4. art as final fallback
    track = _track(art="/library/metadata/3/art/40")
    assert _extract_album_art_uri(queue.metadata_for_track(track, "http://host/s.flac")) == (
        "http://192.168.1.50:32400/library/metadata/3/art/40?X-Plex-Token=secret-token"
    )


def test_metadata_album_art_uses_absolute_url_as_is():
    plex_lib = _make_plex_lib()
    plex_lib.build_url = MagicMock(side_effect=AssertionError("build_url should not be called"))
    queue = _make_queue(plex_lib=plex_lib)

    for url in ("http://cdn.example.com/art.jpg", "https://cdn.example.com/art.png?a=1&b=2"):
        track = _track(thumb=url)
        metadata = queue.metadata_for_track(track, "http://host/s.flac")
        assert _extract_album_art_uri(metadata) == url


def test_metadata_album_art_omitted_when_missing_or_incomplete_plex_lib():
    # No artwork fields on track
    queue = _make_queue(plex_lib=_make_plex_lib())
    assert "<upnp:albumArtURI>" not in queue.metadata_for_track(_track(), "http://host/s.flac")

    # plex_lib is None
    queue_no_lib = _make_queue(plex_lib=None)
    assert "<upnp:albumArtURI>" not in queue_no_lib.metadata_for_track(
        _track(thumb="/library/metadata/1/thumb/10"), "http://host/s.flac"
    )

    # plex_lib missing protocol or address
    for incomplete in (
        _make_plex_lib(protocol="", address="192.168.1.50"),
        _make_plex_lib(protocol="http", address=""),
    ):
        q = _make_queue(plex_lib=incomplete)
        meta = q.metadata_for_track(_track(thumb="/library/metadata/1/thumb/10"), "http://host/s.flac")
        assert "<upnp:albumArtURI>" not in meta
        assert "://:" not in meta


def test_metadata_album_art_uses_pms_address_override_even_if_lib_host_empty(monkeypatch):
    monkeypatch.setattr(play_queue_mod.settings, "pms_address", "10.0.0.5")
    queue = _make_queue(plex_lib=_make_plex_lib(protocol="", address="", port="32400", token="tok"))
    track = _track(thumb="/library/metadata/1/thumb/10")
    metadata = queue.metadata_for_track(track, "http://host/s.flac")
    assert _extract_album_art_uri(metadata) == (
        "http://10.0.0.5:32400/library/metadata/1/thumb/10?X-Plex-Token=tok"
    )
