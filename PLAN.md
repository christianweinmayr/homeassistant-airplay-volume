# AirPlay Speakers - Home Assistant Integration Plan

## Overview

A Home Assistant custom integration (`airplay_speakers`) that discovers AirPlay 1 and AirPlay 2 speakers on the local network and exposes them as media player entities with volume control and TTS announcement capabilities.

## Decisions

| Decision | Choice |
|---|---|
| **Primary use case** | Volume control + TTS announcements |
| **Target devices** | AirPlay 1 + AirPlay 2 (all speakers) |
| **Underlying library** | cliairplay (C binary, based on owntone-server) |
| **Apple TV support** | Works with or without, adapts capabilities |
| **Discovery** | Auto-discovery via mDNS/zeroconf |
| **Binary distribution** | Pre-compiled binaries bundled in the repo |
| **Coexistence** | Independent from built-in Apple TV integration |
| **Distribution target** | HACS custom repository |
| **Domain name** | `airplay_speakers` |
| **Credentials storage** | Per-device in HA config entries |

## Architecture

### File Structure

```
custom_components/airplay_speakers/
  manifest.json          # HACS metadata, zeroconf discovery for _airplay._tcp + _raop._tcp
  __init__.py            # Setup/teardown, cliairplay binary management
  config_flow.py         # Zeroconf auto-discovery + pairing flow (PIN entry)
  const.py               # Domain, defaults, feature flags
  media_player.py        # MediaPlayerEntity (VOLUME_SET, VOLUME_STEP, VOLUME_MUTE, PLAY_MEDIA)
  coordinator.py         # DataUpdateCoordinator polling speaker state
  binary_manager.py      # Manages cliairplay binary (platform detection, extraction, health)
  strings.json           # UI strings for config flow
  translations/en.json   # English translations
  bin/                   # Pre-compiled cliairplay binaries
    cliairplay-linux-x86_64
    cliairplay-linux-aarch64
    cliairplay-darwin-arm64
```

### Component Responsibilities

#### Discovery (config_flow.py)
- HA's zeroconf triggers `async_step_zeroconf()` when `_airplay._tcp.local.` or `_raop._tcp.local.` services appear on the network.
- Filter out devices already managed by the Apple TV integration via unique ID check (use MAC address / device ID from mDNS TXT records).
- Present discovered device to user for confirmation.
- Guide user through PIN-based HAP pairing for AirPlay 2 devices.
- Store pairing credentials in the config entry.

#### Binary Management (binary_manager.py)
- Detect platform (linux x86_64, linux aarch64, darwin arm64).
- Extract/locate the correct pre-compiled cliairplay binary from `bin/`.
- Manage cliairplay as a long-running subprocess or spawn per-command.
- Handle process lifecycle: startup, health checks, crash recovery, graceful shutdown.
- Communicate with cliairplay via its control interface (stdin/stdout, socket, or CLI args depending on its API).

#### Media Player Entity (media_player.py)
- Extends `CoordinatorEntity` and `MediaPlayerEntity`.
- `device_class = MediaPlayerDeviceClass.SPEAKER`
- Supported features:
  - `VOLUME_SET` - absolute volume control (0.0 to 1.0)
  - `VOLUME_STEP` - volume up/down
  - `VOLUME_MUTE` - mute toggle
  - `PLAY_MEDIA` - for TTS audio playback
- Properties: `volume_level`, `is_volume_muted`, `state`
- Device info from mDNS TXT records: name, manufacturer, model, firmware version.

#### State Coordination (coordinator.py)
- `DataUpdateCoordinator` polls speaker state at configurable interval (default 30s).
- Tracks: volume level, mute state, playing state, availability.
- Handles connection errors gracefully with `UpdateFailed`.
- Triggers `async_request_refresh()` after volume/playback commands.

#### TTS Integration
- HA's TTS engine produces audio files (WAV/MP3).
- `async_play_media()` streams TTS audio to the speaker via cliairplay's RAOP/AirPlay 2 streaming.
- Support media types: `music`, `tts`.

#### Apple TV Enhancement (optional)
- When an Apple TV is detected on the network, optionally route commands through it.
- Uses pyatv's MRP protocol for full playback control (play, pause, skip, stop).
- Enables multi-room speaker grouping via `add_output_devices` / `set_output_devices`.
- Adapts `supported_features` dynamically based on Apple TV availability.

### Protocol Details

#### AirPlay 1 (RAOP)
- Discovery: `_raop._tcp.local.`
- Audio streaming: RTSP-based, optional RSA encryption
- Volume: SET_PARAMETER via RTSP
- Simpler authentication (legacy pairing)

#### AirPlay 2
- Discovery: `_airplay._tcp.local.` with feature flags in TXT records
- Authentication: HAP (HomeKit Accessory Protocol) with SRP 3072-bit pairing
- Encryption: ChaCha20-Poly1305 with HKDF-SHA-512 derived keys
- Audio streaming: Buffered mode for lower latency, PTP-based sync for multi-room
- Requires FairPlay v3 authentication for encrypted audio

#### Key mDNS TXT Record Fields
- `features` - capability bitmask (determines AirPlay version)
- `pk` - public key for pairing
- `pi` - pairing identity
- `deviceid` - device MAC address (use as unique ID)
- `model` - hardware model identifier
- `gid` / `hgid` / `igl` - group/leader info for multi-room

### cliairplay Integration

cliairplay is a C binary from the Music Assistant project, based on owntone-server:
- Repository: https://github.com/music-assistant/cliairplay/
- Supports AirPlay 2 encrypted streaming (FairPlay, HAP)
- Handles pairing, authentication, and audio delivery
- Pre-compiled for linux-x86_64 and linux-aarch64 (primary HA targets)

Binary communication options (to investigate):
1. CLI invocation per command (simplest, highest latency)
2. Long-running daemon with control socket (best for state tracking)
3. Stdin/stdout JSON protocol (middle ground)

### Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| cliairplay immaturity | Commands may fail | Fallback to pyatv for basic volume up/down; error handling with retries |
| HomePod OS updates | Apple breaks protocol | Monitor Music Assistant issues; cliairplay tracks owntone-server upstream |
| Binary platform coverage | Missing architectures | Cover x86_64 + aarch64 Linux (HAOS); darwin-arm64 for dev; document building from source |
| Subprocess crashes | Speaker becomes unavailable | Process health monitoring, automatic restart, graceful degradation |
| Network complexity | mDNS fails on VLANs | Manual IP entry as fallback (future enhancement) |
| Coexistence conflicts | Duplicate entities | Check unique IDs against existing integrations during discovery |

## Known Limitations of pyatv (if used as fallback)

- HomePod Mini: `set_volume` commands are sent but ignored (pyatv issue #1300)
- Standalone speakers (RAOP only): play/pause/skip do NOT work (pyatv issue #1068)
- AirPlay 2 encrypted audio streaming: NOT implemented in pyatv
- Metadata: Only available for content pyatv itself is streaming
- Multi-room grouping: Requires Apple TV (MRP protocol), not available for standalone speakers

## Implementation Phases

### Phase 1: Scaffolding + Discovery
- Project structure with all required files
- manifest.json with zeroconf discovery
- Config flow: auto-discovery of AirPlay devices via mDNS
- Basic media player entity (skeleton, no functionality yet)
- HACS repository structure (hacs.json, README, LICENSE)

### Phase 2: cliairplay Integration
- Binary manager: platform detection, extraction, process lifecycle
- Bundle pre-compiled binaries
- Establish communication protocol with cliairplay
- Implement pairing flow in config_flow.py

### Phase 3: Volume Control
- `async_set_volume_level()` via cliairplay
- `async_volume_up()` / `async_volume_down()`
- `async_mute_volume()`
- State polling via coordinator (read current volume)

### Phase 4: TTS / Audio Streaming
- `async_play_media()` implementation
- Stream HA TTS audio files to speakers via cliairplay
- Handle media type detection and conversion

### Phase 5: Apple TV Enhancement (Optional)
- Detect Apple TV on network
- Route commands via pyatv MRP for full playback control
- Speaker grouping support
- Dynamic feature adaptation

### Phase 6: Polish + HACS Release
- Error handling and edge cases
- User-facing documentation
- HACS compliance (branding, releases)
- Testing on multiple device types

## Reference Links

- pyatv: https://pyatv.dev/ / https://github.com/postlund/pyatv
- cliairplay: https://github.com/music-assistant/cliairplay/
- Music Assistant AirPlay docs: https://www.music-assistant.io/player-support/airplay/
- owntone-server: https://github.com/owntone/owntone-server
- HA Developer Docs: https://developers.home-assistant.io/
- HA Media Player Entity: https://developers.home-assistant.io/docs/core/entity/media-player/
- HA Config Flow: https://developers.home-assistant.io/docs/config_entries_config_flow_handler/
- HA Integration Quality Scale: https://developers.home-assistant.io/docs/core/integration-quality-scale/
- HACS Publishing: https://www.hacs.xyz/docs/publish/integration/
- AirPlay 2 Internals: https://emanuelecozzi.net/docs/airplay2/
- openairplay spec: https://openairplay.github.io/airplay-spec/
