"""Constants for the AirPlay Speakers integration."""

from datetime import timedelta

DOMAIN = "airplay_speakers"

DEFAULT_UPDATE_INTERVAL = timedelta(seconds=10)

# Config entry data keys
CONF_ATV_HOST = "atv_host"
CONF_ATV_NAME = "atv_name"
CONF_COMPANION_CREDENTIALS = "companion_credentials"
CONF_AIRPLAY_CREDENTIALS = "airplay_credentials"
