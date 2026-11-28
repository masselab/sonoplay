import sys
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

# Prior test modules (test_adapter_stopped_state.py, test_audio_settings.py)
# stub heavy transitive deps - including dotmap and xmltodict - as bare
# MagicMock modules and never restore them. Only purge entries that actually
# look like a leftover stub, so a legitimately real module already imported
# elsewhere is left alone (consistent with test_audio_settings.py /
# test_xml_unescape.py).
for _key in list(sys.modules):
    if not (_key in ("utils", "dlna", "dlna.dlna_device", "dotmap", "xmltodict", "settings")
            or _key.startswith(("utils.", "dotmap.", "xmltodict.", "settings."))):
        continue
    _mod = sys.modules[_key]
    if isinstance(_mod, MagicMock) or (
        hasattr(_mod, "__file__") and _mod.__file__ and "<stub" in str(_mod.__file__)
    ):
        del sys.modules[_key]

from dlna.dlna_device import DlnaDeviceService
from utils import build_didl_lite_metadata, mime_type_for_container


def test_mime_type_for_known_container():
    assert mime_type_for_container("flac") == "audio/flac"
    assert mime_type_for_container("MP3") == "audio/mpeg"


def test_mime_type_for_dsd_containers():
    assert mime_type_for_container("dsf") == "audio/dsd"
    assert mime_type_for_container("dff") == "audio/dsd"


def test_mime_type_for_unknown_or_missing_container_defaults_to_mpeg():
    assert mime_type_for_container("some-weird-format") == "audio/mpeg"
    assert mime_type_for_container(None) == "audio/mpeg"
    assert mime_type_for_container("") == "audio/mpeg"


def test_didl_lite_is_not_empty_and_contains_res_with_protocol_info():
    """The core regression: CurrentURIMetaData must never be blank.

    Samsung (and other strict) renderers reject SetAVTransportURI with a
    UPnPError SOAP Fault when metadata is empty, because they can't
    classify the resource. This asserts we always produce a populated
    DIDL-Lite document with a res element describing the stream type.
    """
    metadata = build_didl_lite_metadata(
        item_id="12345",
        title="Track Title",
        url="http://192.168.1.50:32400/library/parts/1/file.mp3",
        mime_type="audio/mpeg",
        artist="Some Artist",
        album="Some Album",
        duration_ms=245000,
    )
    assert metadata
    assert "<DIDL-Lite" in metadata
    assert 'protocolInfo="http-get:*:audio/mpeg:*"' in metadata
    assert "<dc:title>Track Title</dc:title>" in metadata
    assert "<upnp:artist>Some Artist</upnp:artist>" in metadata
    assert "<upnp:album>Some Album</upnp:album>" in metadata
    # 245000ms = 4:05.000
    assert 'duration="0:04:05.000"' in metadata


def test_didl_lite_escapes_special_characters_in_metadata():
    """Titles/artists with XML-significant characters must not break the
    DIDL-Lite document (or the outer SOAP envelope it gets embedded in)."""
    metadata = build_didl_lite_metadata(
        item_id="1",
        title="Rock & Roll <Live>",
        url="http://example.com/a.mp3?x=1&y=2",
        mime_type="audio/mpeg",
        artist="AT&T Band",
    )
    assert "<Live>" not in metadata
    assert "Rock &amp; Roll" in metadata
    assert "AT&amp;T Band" in metadata

    # And the DIDL string itself must be valid, well-formed XML on its own
    # (this is what a real renderer parses it back into after the outer SOAP
    # envelope is decoded).
    root = ET.fromstring(metadata)
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    title_el = root.find(".//dc:title", ns)
    assert title_el.text == "Rock & Roll <Live>"


def test_didl_lite_omits_optional_tags_when_absent():
    metadata = build_didl_lite_metadata(
        item_id="1",
        title="Title Only",
        url="http://example.com/a.mp3",
        mime_type="audio/mpeg",
    )
    assert "<upnp:artist>" not in metadata
    assert "<upnp:album>" not in metadata
    assert "<upnp:albumArtURI>" not in metadata
    assert "<dc:creator>" not in metadata
    assert "duration=" not in metadata


def test_didl_lite_includes_and_escapes_album_art_uri():
    art_url = "http://192.168.1.50:32400/library/metadata/10/thumb/1700000000?X-Plex-Token=abc&foo=bar"
    metadata = build_didl_lite_metadata(
        item_id="1",
        title="Track Title",
        url="http://192.168.1.50:32400/library/parts/1/file.mp3?X-Plex-Token=abc",
        album_art_uri=art_url,
    )
    assert "<upnp:albumArtURI>" in metadata
    assert "dlna:profileID" not in metadata
    assert "X-Plex-Token=abc&amp;foo=bar" in metadata

    root = ET.fromstring(metadata)
    ns = {"upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/"}
    art_el = root.find(".//upnp:albumArtURI", ns)
    assert art_el is not None
    assert art_el.text == art_url


def test_didl_lite_omits_album_art_uri_when_none_or_empty():
    for empty_val in (None, ""):
        metadata = build_didl_lite_metadata(
            item_id="1",
            title="Track Title",
            url="http://example.com/a.mp3",
            album_art_uri=empty_val,
        )
        assert "<upnp:albumArtURI>" not in metadata


def test_soap_payload_escapes_current_uri_metadata_with_album_art_uri():
    """Verify DlnaDeviceService.payload_from_template double-escapes CurrentURIMetaData
    so the outer SOAP XML is well-formed and round-trips back to valid DIDL-Lite."""
    art_url = "http://192.168.1.50:32400/library/metadata/10/thumb/1?X-Plex-Token=tok&size=large"
    stream_url = "http://192.168.1.50:32400/library/parts/1/file.flac?X-Plex-Token=tok"
    metadata = build_didl_lite_metadata(
        item_id="10",
        title="Song & Dance",
        url=stream_url,
        mime_type="audio/flac",
        album_art_uri=art_url,
    )

    device = MagicMock()
    device.location_url = "http://192.168.1.99:1400/xml/device_description.xml"
    service = DlnaDeviceService(
        {
            "serviceType": "urn:schemas-upnp-org:service:AVTransport:1",
            "controlURL": "/MediaRenderer/AVTransport/Control",
            "eventSubURL": "/MediaRenderer/AVTransport/Event",
            "SCPDURL": "/xml/AVTransport1.xml",
        },
        device,
    )
    soap_payload = service.payload_from_template(
        "SetAVTransportURI",
        {
            "InstanceID": 0,
            "CurrentURI": stream_url,
            "CurrentURIMetaData": metadata,
        },
    )

    soap_root = ET.fromstring(soap_payload)
    meta_el = soap_root.find(".//CurrentURIMetaData")
    assert meta_el is not None
    assert meta_el.text == metadata

    didl_root = ET.fromstring(meta_el.text)
    ns = {"upnp": "urn:schemas-upnp-org:metadata-1-0/upnp/"}
    art_el = didl_root.find(".//upnp:albumArtURI", ns)
    assert art_el is not None
    assert art_el.text == art_url


def test_didl_lite_falls_back_to_item_id_zero_when_missing():
    metadata = build_didl_lite_metadata(
        item_id=None,
        title="Title",
        url="http://example.com/a.mp3",
        mime_type="audio/mpeg",
    )
    assert 'id="0"' in metadata
