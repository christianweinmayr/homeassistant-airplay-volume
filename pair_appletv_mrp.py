#!/usr/bin/env python3
"""Pair with Apple TV via MRP protocol (for volume and media control)."""

import asyncio
import json
from pathlib import Path

import pyatv
from pyatv.const import Protocol

CRED_FILE = Path(__file__).parent / ".atv_credentials.json"


async def main():
    loop = asyncio.get_event_loop()
    configs = await pyatv.scan(loop, hosts=["10.0.42.252"], timeout=5)
    if not configs:
        print("Apple TV not found!")
        return

    config = configs[0]
    print(f"Found: {config.name}")
    print("Check your TV for a PIN code...")

    pairing = await pyatv.pair(config, Protocol.MRP, loop)
    await pairing.begin()

    pin = input("Enter PIN from TV: ").strip()
    pairing.pin(int(pin))

    await pairing.finish()

    creds = pairing.service.credentials
    print("MRP pairing successful!")

    data = {}
    if CRED_FILE.exists():
        data = json.loads(CRED_FILE.read_text())
    data["mrp"] = creds
    CRED_FILE.write_text(json.dumps(data, indent=2))
    print(f"Credentials saved to {CRED_FILE}")

    await pairing.close()


if __name__ == "__main__":
    asyncio.run(main())
