"""Constants for the AirPlay Speakers integration."""

from datetime import timedelta

DOMAIN = "airplay_speakers"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=30)

# mDNS service types
MDNS_AIRPLAY_SERVICE = "_airplay._tcp.local."
MDNS_RAOP_SERVICE = "_raop._tcp.local."

# mDNS TXT record keys
TXT_DEVICE_ID = "deviceid"
TXT_MODEL = "model"
TXT_FEATURES = "features"
TXT_PUBLIC_KEY = "pk"
TXT_PAIRING_ID = "pi"

# Config entry data keys
CONF_DEVICE_ID = "device_id"
CONF_CREDENTIALS = "credentials"
CONF_MODEL = "model"

# Apple TV
CONF_APPLE_TV_ID = "apple_tv_identifier"

# Binary names
BINARY_NAME = "cliairplay"
