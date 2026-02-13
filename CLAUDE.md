# AirPlay Speakers - Home Assistant Custom Integration

## Project Overview

This is a Home Assistant custom integration (`airplay_speakers`) that discovers AirPlay 1 and AirPlay 2 speakers on the local network and exposes them as `media_player` entities. Primary capabilities: volume control and TTS announcements. Distributed via HACS.

## Key Architecture Decisions

- **Domain**: `airplay_speakers` — all files live under `custom_components/airplay_speakers/`
- **Core library**: `cliairplay` C binary (from Music Assistant, based on owntone-server) for AirPlay 2 support. NOT pyatv (which lacks AirPlay 2 encrypted streaming).
- **Binary distribution**: Pre-compiled cliairplay binaries bundled in `custom_components/airplay_speakers/bin/` for linux-x86_64, linux-aarch64, and darwin-arm64.
- **Discovery**: Auto-discovery only via mDNS/zeroconf (`_airplay._tcp.local.` and `_raop._tcp.local.`). No manual IP entry.
- **Coexistence**: Runs independently alongside the built-in Apple TV integration. Must not conflict — filter out devices already managed by Apple TV integration during discovery using unique ID checks.
- **Credentials**: Per-device HAP pairing credentials stored in each device's HA config entry.
- **Apple TV**: When an Apple TV is present on the network, the integration can optionally route commands through it (via pyatv MRP protocol) for enhanced capabilities (playback control, speaker grouping). Without an Apple TV, only volume control and TTS are available.

## File Structure

```
custom_components/airplay_speakers/
  manifest.json          # Integration metadata, zeroconf discovery
  __init__.py            # Entry point: async_setup_entry / async_unload_entry
  config_flow.py         # Zeroconf discovery + HAP pairing config flow
  const.py               # DOMAIN = "airplay_speakers", constants
  media_player.py        # MediaPlayerEntity subclass (speaker device_class)
  coordinator.py         # DataUpdateCoordinator for state polling
  binary_manager.py      # cliairplay binary lifecycle management
  strings.json           # Config flow UI strings
  translations/en.json   # English translations
  bin/                   # Pre-compiled cliairplay binaries
```

## Entity Design

- Platform: `media_player`
- Device class: `speaker`
- Supported features: `VOLUME_SET | VOLUME_STEP | VOLUME_MUTE | PLAY_MEDIA`
- Entity extends both `CoordinatorEntity` and `MediaPlayerEntity`
- Unique ID: Device MAC address / deviceid from mDNS TXT records (never use IP)
- State polling: `DataUpdateCoordinator` with 30s default interval

## Technical Context

### AirPlay Protocol
- AirPlay 1 (RAOP): RTSP-based, optional RSA encryption, simpler pairing
- AirPlay 2: HAP authentication (SRP 3072-bit), ChaCha20-Poly1305 encryption, FairPlay v3 for audio, buffered streaming
- Discovery via mDNS: service types `_airplay._tcp.local.` and `_raop._tcp.local.`
- Key TXT record fields: `deviceid` (MAC, use as unique ID), `model`, `features` (capability bitmask), `pk`, `pi`, `gid`/`hgid`/`igl` (grouping)

### cliairplay
- Repository: https://github.com/music-assistant/cliairplay/
- C binary based on owntone-server, purpose-built for Music Assistant
- Handles: AirPlay 2 HAP pairing, FairPlay authentication, encrypted audio streaming, volume control
- Must be managed as a subprocess from Python (startup, health monitoring, crash recovery, shutdown)

### pyatv (secondary, for Apple TV MRP only)
- Repository: https://github.com/postlund/pyatv
- Only used when an Apple TV is present for MRP protocol commands
- Known limitations: HomePod Mini ignores set_volume (issue #1300), no playback control on standalone speakers via RAOP (issue #1068), no AirPlay 2 encrypted streaming
- DO NOT use pyatv for direct AirPlay speaker control — use cliairplay instead

### Home Assistant Patterns
- Config entries with config flow (NO YAML configuration)
- `async_setup_entry()` / `async_unload_entry()` lifecycle
- `DataUpdateCoordinator` for centralized polling
- `CoordinatorEntity` base class for entities
- Device registry via `device_info` property on entities
- `ConfigEntryAuthFailed` for auth errors, `UpdateFailed` for connection errors
- `async_request_refresh()` after entity actions (volume set, play media)

## Implementation Phases

See PLAN.md for the full phased implementation plan. Summary:
1. Scaffolding + mDNS discovery
2. cliairplay binary integration
3. Volume control
4. TTS / audio streaming
5. Apple TV enhancement (optional)
6. Polish + HACS release

## HACS Requirements

- One integration per repo
- `manifest.json` must have: domain, documentation, issue_tracker, codeowners, name, version
- `hacs.json` at repo root
- GitHub releases for version management
- Register branding at home-assistant/brands (optional but recommended)

## Testing Notes

- Test on real AirPlay speakers — protocol behavior varies significantly between manufacturers
- HomePod Mini has known volume control issues
- Samsung AirPlay 2 TVs have known compatibility issues with third-party implementations
- Apple OS updates (HomePod OS, tvOS) frequently break protocol compatibility
- Test both AirPlay 1 (e.g., AirPort Express) and AirPlay 2 (e.g., HomePod) devices
- Verify coexistence with Apple TV integration — no duplicate entities

## Reference Links

- Plan: ./PLAN.md
- cliairplay: https://github.com/music-assistant/cliairplay/
- pyatv docs: https://pyatv.dev/
- HA developer docs: https://developers.home-assistant.io/
- HA media player entity: https://developers.home-assistant.io/docs/core/entity/media-player/
- HA config flow: https://developers.home-assistant.io/docs/config_entries_config_flow_handler/
- HA coordinator pattern: https://developers.home-assistant.io/docs/integration_fetching_data/
- HACS publishing: https://www.hacs.xyz/docs/publish/integration/
- AirPlay 2 internals: https://emanuelecozzi.net/docs/airplay2/
- Music Assistant AirPlay: https://www.music-assistant.io/player-support/airplay/
