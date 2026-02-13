# AirPlay Speakers for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Control your AirPlay speakers directly from Home Assistant. Discover speakers automatically, adjust volume, send TTS announcements, and -- with an Apple TV on the network -- get full playback control.

---

## What This Does

This custom integration discovers AirPlay 1 and AirPlay 2 speakers on your local network and exposes them as `media_player` entities. You get volume control and TTS out of the box. If an Apple TV is present, you also get play/pause/skip and multi-room speaker grouping.

### Capabilities

| Feature | Without Apple TV | With Apple TV |
|---|:---:|:---:|
| Auto-discovery via mDNS | :white_check_mark: | :white_check_mark: |
| Volume set / step up / step down | :white_check_mark: | :white_check_mark: |
| Mute / unmute | :white_check_mark: | :white_check_mark: |
| TTS announcements | :white_check_mark: | :white_check_mark: |
| Play / pause / stop | :x: | :white_check_mark: |
| Next / previous track | :x: | :white_check_mark: |
| Now playing (title, artist) | :x: | :white_check_mark: |
| Multi-room speaker grouping | :x: | :white_check_mark: |

### Supported Devices

- **AirPlay 2**: HomePod, HomePod Mini, and other AirPlay 2 speakers
- **AirPlay 1**: AirPort Express, older AirPlay receivers
- **AirPlay-compatible**: Sound bars, AVRs, and third-party speakers with AirPlay support

## How It Works

```
Home Assistant
    |
    +-- zeroconf discovers _airplay._tcp / _raop._tcp
    |
    +-- cliairplay binary (based on owntone-server)
    |       Handles: HAP pairing, FairPlay auth,
    |       AirPlay 2 encrypted streaming, volume control
    |
    +-- pyatv (optional, when Apple TV is available)
            Handles: MRP playback control,
            speaker grouping, now-playing metadata
```

The core audio path uses [cliairplay](https://github.com/music-assistant/cliairplay/) -- a purpose-built C binary from the Music Assistant project. Unlike pyatv, it fully supports AirPlay 2 encrypted streaming (HAP authentication, FairPlay v3, ChaCha20-Poly1305).

Speakers are discovered automatically via mDNS. AirPlay 2 devices require a one-time PIN pairing step. AirPlay 1 devices work immediately.

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

After installation, speakers are discovered automatically. You'll see a notification for each new speaker:

1. **AirPlay 1 devices** -- confirm and you're done
2. **AirPlay 2 devices** -- confirm, then enter the PIN displayed on your speaker to complete HAP pairing

Credentials are stored per-device in the config entry. No YAML configuration needed.

## Coexistence with Apple TV Integration

This integration runs independently alongside the built-in Apple TV integration. During discovery, devices already managed by Apple TV are automatically filtered out -- no duplicate entities.

## Architecture

```
custom_components/airplay_speakers/
  __init__.py          # Entry point, lifecycle management
  config_flow.py       # Zeroconf discovery + HAP pairing
  const.py             # Domain constants
  media_player.py      # MediaPlayerEntity (speaker device class)
  coordinator.py       # DataUpdateCoordinator (30s polling)
  binary_manager.py    # cliairplay subprocess management
  apple_tv.py          # Optional pyatv MRP bridge
  manifest.json        # Integration metadata
  strings.json         # Config flow UI strings
  translations/en.json # English translations
  bin/                 # Pre-compiled cliairplay binaries
```

## Troubleshooting

### Speaker not discovered
- Verify the speaker is on the **same subnet** as Home Assistant
- Ensure mDNS traffic is not blocked by your router/firewall
- Restart the speaker and wait ~60 seconds for re-announcement

### AirPlay 2 pairing fails
- Enter the PIN promptly -- it may time out
- Power-cycle the speaker and retry
- Check HA logs (`Logger: custom_components.airplay_speakers`) for details

### Volume commands ignored
- HomePod Mini has known issues with third-party volume control
- Some Samsung AirPlay 2 TVs have limited third-party compatibility
- Check if the speaker has restrictions enabled (parental controls, etc.)

### Entity shows unavailable
- The cliairplay process may have crashed -- check logs for auto-restart messages
- Verify the speaker is powered on and network-reachable
- The integration retries up to 5 times with exponential backoff before giving up

### Duplicate entities
- This integration filters out devices managed by the built-in Apple TV integration
- If duplicates appear, remove the device and let it be re-discovered

## Requirements

- Home Assistant 2024.1.0+
- AirPlay speakers on the same local network
- cliairplay binaries in `bin/` (bundled for linux-x86_64, linux-aarch64, darwin-arm64)

## License

MIT -- see [LICENSE](LICENSE).
