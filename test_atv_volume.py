#!/usr/bin/env python3
"""Test volume control through Apple TV (after pairing).

Usage:
    python3 test_atv_volume.py                          # Show status
    python3 test_atv_volume.py --volume 30              # Set Apple TV volume to 30
    python3 test_atv_volume.py --device office --volume 25  # Set "office" speaker to 25
"""

import argparse
import asyncio
import json
from pathlib import Path

import pyatv
from pyatv.const import Protocol, FeatureName
from pyatv.interface import OutputDevice

CRED_FILE = Path(__file__).parent / ".atv_credentials.json"


async def main(target_volume: int | None = None, device_name: str | None = None):
    creds = json.loads(CRED_FILE.read_text())
    host = creds["host"]

    loop = asyncio.get_event_loop()
    configs = await pyatv.scan(loop, hosts=[host], timeout=5)
    if not configs:
        print("Apple TV not found!")
        return

    config = configs[0]

    # Add all available credentials
    if "companion" in creds:
        config.set_credentials(Protocol.Companion, creds["companion"])
    if "airplay" in creds:
        config.set_credentials(Protocol.AirPlay, creds["airplay"])
    if "mrp" in creds:
        config.set_credentials(Protocol.MRP, creds["mrp"])

    print(f"Connecting to {config.name}...")
    atv = await pyatv.connect(config, loop)

    try:
        # Volume
        print(f"\nApple TV volume: {atv.audio.volume}")

        # Output devices (grouped speakers)
        print(f"\nOutput devices:")
        devices = []
        try:
            devices = atv.audio.output_devices
            for d in devices:
                print(f"  {d.name}: volume={d.volume}, id={d.identifier}")
        except Exception as e:
            print(f"  Not available: {e}")

        # Features
        print(f"\nFeatures:")
        for fname in [FeatureName.Volume, FeatureName.SetVolume,
                      FeatureName.VolumeUp, FeatureName.VolumeDown,
                      FeatureName.OutputDevices, FeatureName.SetOutputDevices,
                      FeatureName.AddOutputDevices, FeatureName.RemoveOutputDevices]:
            info = atv.features.get_feature(fname)
            print(f"  {fname.name}: {info.state.name}")

        # Playing state
        playing = await atv.metadata.playing()
        print(f"\nPlaying: state={playing.device_state}")
        if playing.title:
            print(f"  title: {playing.title}")
        if playing.artist:
            print(f"  artist: {playing.artist}")

        # Set volume if requested
        if target_volume is not None:
            if device_name:
                # Find the device by name
                target_dev = None
                for d in devices:
                    if d.name and d.name.lower() == device_name.lower():
                        target_dev = d
                        break
                if not target_dev:
                    print(f"\nDevice '{device_name}' not found in output devices!")
                    print("Available devices:", [d.name for d in devices])
                    return

                print(f"\nSetting volume on '{target_dev.name}' "
                      f"(id={target_dev.identifier}) to {target_volume}...")
                await atv.audio.set_volume(
                    float(target_volume),
                    output_device=target_dev
                )
            else:
                print(f"\nSetting Apple TV volume to {target_volume}...")
                await atv.audio.set_volume(float(target_volume))

            await asyncio.sleep(2)
            print(f"\nAfter volume change:")
            print(f"  Apple TV volume: {atv.audio.volume}")
            try:
                for d in atv.audio.output_devices:
                    print(f"  {d.name}: volume={d.volume}")
            except Exception:
                pass

    finally:
        atv.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume", type=int, help="Set volume (0-100)")
    parser.add_argument("--device", type=str, help="Target output device name")
    args = parser.parse_args()
    asyncio.run(main(args.volume, args.device))
