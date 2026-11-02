"""Constants for EZVIZ Live."""

DOMAIN = "ezviz_live"

EZVIZ_DOMAIN = "ezviz"
EZVIZ_TYPE_CLOUD = "EZVIZ_CLOUD_ACCOUNT"

CONF_EZVIZ_ENTRY_ID = "ezviz_entry_id"
CONF_CLIENT_KEY = "client_key"
CONF_AREA_SYNCED = "area_synced"  # serials whose linked device already got the core device's area

CONF_STREAM_TYPE = "stream_type"  # 1 = main, 2 = sub
CONF_ALLOW_WEBRTC = "allow_webrtc"  # False = HLS only, go2rtc does not take the camera
DEFAULT_STREAM_TYPE = 1
DEFAULT_ALLOW_WEBRTC = False
