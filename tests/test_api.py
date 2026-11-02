"""parse_channels: pagelist → live channels (shape taken from a real DP2C account, serials made up)."""

import base64

from custom_components.ezviz_live.api import parse_channels

KEY = base64.b64encode(b"\x30" * 91).decode()


def vtm(port=8554):
    return {"domain": "vtm.example.com", "externalIp": "203.0.113.1", "port": port, "tlsPort": 0,
            "publicKey": {"key": KEY, "version": 1}}


def test_dp2c_camera_resource_and_model_names():
    page = {
        "deviceInfos": [{"deviceSerial": "AA0000001", "name": "Front door", "deviceType": "CS-DP2C-R100-6E2WPFB-GD",
                         "deviceSubCategory": "DP2C", "version": "V5.3.3 build 250911", "status": 1}],
        # type 0 is the device itself, type 50 the camera; only the camera resource has a VTM entry
        "resourceInfos": [
            {"resourceId": "r0", "deviceSerial": "AA0000001", "localIndex": "0", "resourceType": 0,
             "streamBizUrl": "biz=1", "resourceName": "Front door"},
            {"resourceId": "r50", "deviceSerial": "AA0000001", "localIndex": "1", "resourceType": 50,
             "streamBizUrl": "biz=1", "resourceName": "Front door"},
        ],
        "VTM": {"r50": vtm()},
        "STATUS": {"AA0000001": {"isEncrypt": 0}},
    }
    channels = parse_channels(page)
    assert list(channels) == ["AA0000001_1"]
    ch = channels["AA0000001_1"]
    assert (ch.model, ch.model_id) == ("DP2C", "CS-DP2C-R100-6E2WPFB-GD")
    assert ch.channel == 1 and ch.channels_on_device == 1 and ch.stream_biz == "biz=1"
    assert ch.vtm_host == "vtm.example.com" and ch.vtm_key == b"\x30" * 91 and ch.vtm_key_version == 1
    assert ch.online and not ch.image_encrypted


def test_multichannel_and_encryption_and_fallbacks():
    page = {
        "deviceInfos": [{"deviceSerial": "NVR000001", "name": "NVR", "deviceType": "CS-X5S-8W", "status": 2}],
        "resourceInfos": [
            {"resourceId": f"c{i}", "deviceSerial": "NVR000001", "localIndex": str(i), "resourceName": f"Cam {i}"}
            for i in (1, 2)
        ],
        "VTM": {"c1": vtm(), "c2": {"externalIp": "203.0.113.2", "port": "8554"}},
        "STATUS": {"NVR000001": {"isEncrypt": 1}},
    }
    channels = parse_channels(page)
    assert sorted(channels) == ["NVR000001_1", "NVR000001_2"]
    c2 = channels["NVR000001_2"]
    assert c2.channels_on_device == 2 and c2.channel_name == "Cam 2"
    assert c2.model == "CS-X5S-8W"  # no deviceSubCategory: fall back to the product code
    assert c2.vtm_host == "203.0.113.2" and c2.vtm_key is None  # no public key → clear-text path
    assert c2.image_encrypted and not c2.online
