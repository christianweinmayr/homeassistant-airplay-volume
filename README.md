# AirPlay Speakers for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](LICENSE)

Control the volume of your AirPlay speakers from Home Assistant -- with a slider directly on the dashboard.

---

## What This Does

This custom integration connects to your Apple TV and discovers the AirPlay speakers in its output group. Each speaker gets a volume slider (shown directly on the default dashboard) and a media player entity displaying the current playback state, title, and artist.

### Features

- Auto-detect Apple TVs on the network (no manual IP entry)
- DHCP-resilient: reconnects by device identifier, not IP address
- Volume slider directly on the dashboard (no card configuration needed)
- Playback state with media title and artist
- Individual volume control per speaker in the group

### Requirements

- An **Apple TV** on the same network (used as the control bridge)
- AirPlay speakers grouped with the Apple TV
- Home Assistant 2024.1.0+

## How It Works

```
Home Assistant
    |
    +-- pyatv: scan network for Apple TVs
    |
    +-- Companion protocol: output device discovery,
    |   volume control per speaker, playback state
    |
    +-- AirPlay protocol: authentication
```

The integration connects to your Apple TV via the Companion and AirPlay protocols. Through the Apple TV's output devices API, it can read and set the volume of each individual AirPlay speaker in the group, and get the current playback state with media metadata.

## Installation

### HACS (Recommended)

1. Open **HACS** > **Integrations** > three-dot menu > **Custom repositories**
2. Add `https://github.com/christianweinmayr/homeassistant-airplay-volume` as an **Integration**
3. Search for **AirPlay Speakers** and install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/airplay_speakers/` into your HA `custom_components/` directory
2. Restart Home Assistant

## Setup

1. Go to **Settings** > **Devices & Services** > **Add Integration** > **AirPlay Speakers**
2. The integration scans your network and shows discovered Apple TVs -- select yours
3. **Step 1/2**: Enter the PIN shown on your TV (Companion protocol pairing)
4. **Step 2/2**: Enter the new PIN shown on your TV (AirPlay protocol pairing)

That's it. Speakers in the Apple TV's output group appear automatically as entities.

### Entities Created Per Speaker

| Entity | Type | Purpose |
|---|---|---|
| `number.<speaker>_volume` | Number (slider) | Volume control, shown directly on dashboard |
| `media_player.<speaker>` | Media Player | Playback state, title, artist |

## Architecture

```
custom_components/airplay_speakers/
  __init__.py          # Entry point, Apple TV connection
  config_flow.py       # Network scan + two-step pairing
  const.py             # Domain constants
  number.py            # Volume slider entity (NumberEntity)
  media_player.py      # Playback state entity (MediaPlayerEntity)
  coordinator.py       # DataUpdateCoordinator (10s polling)
  manifest.json        # Integration metadata
  strings.json         # Config flow UI strings
  translations/en.json # English translations
```

## Troubleshooting

### Apple TV not found during setup
- Verify the Apple TV is on the **same subnet** as Home Assistant
- Ensure mDNS traffic is not blocked by your router/firewall
- The Apple TV must be powered on (not in deep sleep)

### Pairing fails
- Enter the PIN promptly -- it may time out
- If it fails, retry the setup flow
- Check HA logs (`Logger: custom_components.airplay_speakers`) for details

### Volume changes have no effect
- The speaker must be in the Apple TV's active output group
- Check that the speaker appears in `output_devices` (visible in the entity attributes)

### Speaker entity shows unavailable
- The speaker may have been removed from the Apple TV's output group
- Verify the speaker is powered on and network-reachable
- The coordinator retries automatically every 10 seconds

## License

CC BY-NC 4.0 -- see [LICENSE](LICENSE). Free for personal and non-commercial use.
