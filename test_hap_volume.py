#!/usr/bin/env python3
"""Test HAP volume control on AirPlay speakers.

Uses raw HTTP + aiohomekit's crypto utilities for HAP pair-setup/pair-verify.

Usage:
    python3 test_hap_volume.py pair   --host 10.0.42.79 --port 33213 --code 822-34-842
    python3 test_hap_volume.py list   --host 10.0.42.79 --port 33213
    python3 test_hap_volume.py get    --host 10.0.42.79 --port 33213
    python3 test_hap_volume.py set    --host 10.0.42.79 --port 33213 --value 30
"""

import argparse
import asyncio
import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

from aiohomekit.protocol.tlv import TLV
from aiohomekit.protocol import SrpClient

PAIRING_FILE = Path(__file__).parent / ".hap_pairings.json"


def load_pairings() -> dict:
    if PAIRING_FILE.exists():
        return json.loads(PAIRING_FILE.read_text())
    return {}


def save_pairings(pairings: dict):
    PAIRING_FILE.write_text(json.dumps(pairings, indent=2))


def hkdf_derive(input_key: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA512(), length=length, salt=salt, info=info)
    return hkdf.derive(input_key)


class HapSession:
    """Manages an encrypted HAP HTTP session."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.encrypt_key: bytes | None = None
        self.decrypt_key: bytes | None = None
        self.send_counter = 0
        self.recv_counter = 0

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    async def http_request(self, method: str, path: str, body: bytes = b"",
                           content_type: str = "application/pairing+tlv8") -> bytes:
        """Send an HTTP request and return the response body."""
        headers = f"{method} {path} HTTP/1.1\r\nHost: {self.host}\r\n"
        if body:
            headers += f"Content-Length: {len(body)}\r\nContent-Type: {content_type}\r\n"
        headers += "\r\n"

        if self.encrypt_key:
            return await self._encrypted_request(headers.encode() + body)
        else:
            self.writer.write(headers.encode() + body)
            await self.writer.drain()
            return await self._read_http_response()

    async def _read_http_response(self) -> bytes:
        """Read a plain HTTP response."""
        # Read status line
        status_line = await self.reader.readline()
        status_code = int(status_line.split()[1])

        # Read headers
        content_length = 0
        while True:
            line = await self.reader.readline()
            if line == b"\r\n":
                break
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":")[1].strip())

        # Read body
        body = b""
        if content_length > 0:
            body = await self.reader.readexactly(content_length)

        if status_code >= 400:
            raise Exception(f"HTTP {status_code}: {body[:200]}")

        return body

    async def _encrypted_request(self, data: bytes) -> bytes:
        """Send encrypted data and read encrypted response."""
        encrypted = self._encrypt(data)
        self.writer.write(encrypted)
        await self.writer.drain()
        return await self._read_encrypted_response()

    def _encrypt(self, data: bytes) -> bytes:
        """Encrypt data for sending."""
        result = b""
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 1024]
            length = len(chunk)
            nonce = struct.pack("<Q", self.send_counter).ljust(12, b"\x00")
            aad = struct.pack("<H", length)
            cipher = ChaCha20Poly1305(self.encrypt_key)
            encrypted = cipher.encrypt(nonce, chunk, aad)
            result += aad + encrypted
            self.send_counter += 1
            offset += length
        return result

    async def _read_encrypted_response(self) -> bytes:
        """Read and decrypt response data."""
        result = b""
        while True:
            # Read length (2 bytes)
            length_bytes = await self.reader.readexactly(2)
            length = struct.unpack("<H", length_bytes)[0]

            # Read encrypted chunk + auth tag (16 bytes)
            encrypted = await self.reader.readexactly(length + 16)

            nonce = struct.pack("<Q", self.recv_counter).ljust(12, b"\x00")
            cipher = ChaCha20Poly1305(self.decrypt_key)
            decrypted = cipher.decrypt(nonce, encrypted, length_bytes)
            result += decrypted
            self.recv_counter += 1

            # Check if we have a complete HTTP response
            if b"\r\n\r\n" in result:
                # Parse content-length
                header_end = result.index(b"\r\n\r\n") + 4
                headers = result[:header_end].decode("utf-8", errors="replace")
                cl = 0
                for line in headers.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        cl = int(line.split(":")[1].strip())
                body = result[header_end:]
                if len(body) >= cl:
                    return body[:cl]

    async def encrypted_get_json(self, path: str) -> dict:
        """GET JSON over encrypted session."""
        body = await self.http_request("GET", path, content_type="application/hap+json")
        return json.loads(body) if body else {}

    async def encrypted_put_json(self, path: str, data: dict) -> dict | None:
        """PUT JSON over encrypted session."""
        body_bytes = json.dumps(data).encode()
        resp = await self.http_request("PUT", path, body=body_bytes,
                                       content_type="application/hap+json")
        return json.loads(resp) if resp else None


async def pair_setup(session: HapSession, pin: str) -> dict:
    """Perform HAP pair-setup (SRP-6a + ed25519 key exchange).

    Returns dict with pairing keys for future pair-verify.
    """
    await session.connect()

    # === M1: Client -> Server (start request) ===
    print("  M1: Starting pair-setup...")
    m1 = TLV.encode_list([
        (TLV.kTLVType_State, TLV.M1),
        (TLV.kTLVType_Method, TLV.PairSetup),
    ])
    resp = await session.http_request("POST", "/pair-setup", m1)
    m2 = TLV.decode_bytearray(bytearray(resp))

    # Check for errors
    if TLV.kTLVType_Error in m2:
        error = m2[TLV.kTLVType_Error]
        raise Exception(f"M2 error: {error.hex()} (device may need to be reset or is already paired)")

    salt = m2[TLV.kTLVType_Salt]
    server_pk = m2[TLV.kTLVType_PublicKey]
    print(f"  M2: Got salt ({len(salt)} bytes) and server public key ({len(server_pk)} bytes)")

    # === M3: Client -> Server (SRP proof) ===
    print("  M3: Computing SRP proof...")
    srp = SrpClient("Pair-Setup", pin)
    srp.set_salt(int.from_bytes(salt, "big"))
    srp.set_server_public_key(int.from_bytes(server_pk, "big"))

    client_pk = srp.get_public_key_bytes()
    client_proof = srp.get_proof_bytes()

    m3 = TLV.encode_list([
        (TLV.kTLVType_State, TLV.M3),
        (TLV.kTLVType_PublicKey, client_pk),
        (TLV.kTLVType_Proof, client_proof),
    ])
    resp = await session.http_request("POST", "/pair-setup", m3)
    m4 = TLV.decode_bytearray(bytearray(resp))

    if TLV.kTLVType_Error in m4:
        error = m4[TLV.kTLVType_Error]
        raise Exception(f"M4 error: {error.hex()} (wrong PIN?)")

    server_proof = m4[TLV.kTLVType_Proof]
    if not srp.verify_servers_proof_bytes(server_proof):
        raise Exception("Server proof verification failed!")
    print("  M4: SRP verified successfully")

    # === M5: Client -> Server (encrypted ed25519 exchange) ===
    print("  M5: Exchanging long-term keys...")
    session_key = srp.get_session_key_bytes()

    # Derive encryption key for M5
    ios_device_key = Ed25519PrivateKey.generate()
    ios_device_pk = ios_device_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    controller_id = "10:10:10:10:10:10"  # Our controller ID

    ios_device_x = hkdf_derive(session_key, b"Pair-Setup-Controller-Sign-Salt",
                                b"Pair-Setup-Controller-Sign-Info", 32)
    ios_device_info = ios_device_x + controller_id.encode() + ios_device_pk
    ios_device_sig = ios_device_key.sign(ios_device_info)

    sub_tlv = TLV.encode_list([
        (TLV.kTLVType_Identifier, controller_id.encode()),
        (TLV.kTLVType_PublicKey, ios_device_pk),
        (TLV.kTLVType_Signature, ios_device_sig),
    ])

    # Encrypt with session key
    enc_key = hkdf_derive(session_key, b"Pair-Setup-Encrypt-Salt",
                           b"Pair-Setup-Encrypt-Info", 32)
    cipher = ChaCha20Poly1305(enc_key)
    nonce = b"\x00\x00\x00\x00PS-Msg05"
    encrypted = cipher.encrypt(nonce, bytes(sub_tlv), b"")

    m5 = TLV.encode_list([
        (TLV.kTLVType_State, TLV.M5),
        (TLV.kTLVType_EncryptedData, encrypted),
    ])
    resp = await session.http_request("POST", "/pair-setup", m5)
    m6 = TLV.decode_bytearray(bytearray(resp))

    if TLV.kTLVType_Error in m6:
        error = m6[TLV.kTLVType_Error]
        raise Exception(f"M6 error: {error.hex()}")

    # Decrypt M6 to get accessory's long-term public key
    m6_encrypted = m6[TLV.kTLVType_EncryptedData]
    nonce6 = b"\x00\x00\x00\x00PS-Msg06"
    decrypted = cipher.decrypt(nonce6, bytes(m6_encrypted), b"")
    m6_sub = TLV.decode_bytearray(bytearray(decrypted))

    accessory_id = m6_sub[TLV.kTLVType_Identifier].decode()
    accessory_ltpk = m6_sub[TLV.kTLVType_PublicKey]

    print(f"  M6: Pairing complete! Accessory ID: {accessory_id}")

    # Save pairing data
    ios_device_ltsk = ios_device_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )

    return {
        "iOSDeviceLTSK": ios_device_ltsk.hex(),
        "iOSDeviceLTPK": ios_device_pk.hex(),
        "iOSPairingId": controller_id,
        "AccessoryLTPK": accessory_ltpk.hex(),
        "AccessoryPairingID": accessory_id,
        "AccessoryAddress": session.host,
        "AccessoryPort": session.port,
    }


async def pair_verify(session: HapSession, pairing: dict):
    """Perform HAP pair-verify to establish an encrypted session."""
    await session.connect()

    # Generate ephemeral X25519 key pair
    our_key = X25519PrivateKey.generate()
    our_pk = our_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    # === M1: Send our ephemeral public key ===
    m1 = TLV.encode_list([
        (TLV.kTLVType_State, TLV.M1),
        (TLV.kTLVType_PublicKey, our_pk),
    ])
    resp = await session.http_request("POST", "/pair-verify", m1)
    m2 = TLV.decode_bytearray(bytearray(resp))

    if TLV.kTLVType_Error in m2:
        raise Exception(f"pair-verify M2 error: {m2[TLV.kTLVType_Error].hex()}")

    # Get server's ephemeral key and encrypted data
    server_pk_bytes = m2[TLV.kTLVType_PublicKey]
    encrypted_data = m2[TLV.kTLVType_EncryptedData]

    # Compute shared secret
    server_pk = X25519PublicKey.from_public_bytes(server_pk_bytes)
    shared_secret = our_key.exchange(server_pk)

    # Derive session key
    session_key = hkdf_derive(shared_secret, b"Pair-Verify-Encrypt-Salt",
                               b"Pair-Verify-Encrypt-Info", 32)

    # Decrypt server's sub-TLV
    cipher = ChaCha20Poly1305(session_key)
    nonce = b"\x00\x00\x00\x00PV-Msg02"
    decrypted = cipher.decrypt(nonce, bytes(encrypted_data), b"")
    sub_tlv = TLV.decode_bytearray(bytearray(decrypted))

    server_id = sub_tlv[TLV.kTLVType_Identifier].decode()
    server_sig = sub_tlv[TLV.kTLVType_Signature]

    # Verify server's signature using stored AccessoryLTPK
    accessory_ltpk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pairing["AccessoryLTPK"]))
    server_info = server_pk_bytes + server_id.encode() + our_pk
    accessory_ltpk.verify(bytes(server_sig), server_info)

    # === M3: Send our proof ===
    ios_ltsk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(pairing["iOSDeviceLTSK"]))
    ios_ltpk = bytes.fromhex(pairing["iOSDeviceLTPK"])
    ios_id = pairing["iOSPairingId"]

    ios_info = our_pk + ios_id.encode() + server_pk_bytes
    ios_sig = ios_ltsk.sign(ios_info)

    sub_tlv3 = TLV.encode_list([
        (TLV.kTLVType_Identifier, ios_id.encode()),
        (TLV.kTLVType_Signature, ios_sig),
    ])

    nonce3 = b"\x00\x00\x00\x00PV-Msg03"
    encrypted3 = cipher.encrypt(nonce3, bytes(sub_tlv3), b"")

    m3 = TLV.encode_list([
        (TLV.kTLVType_State, TLV.M3),
        (TLV.kTLVType_EncryptedData, encrypted3),
    ])
    resp = await session.http_request("POST", "/pair-verify", m3)
    m4 = TLV.decode_bytearray(bytearray(resp))

    if TLV.kTLVType_Error in m4:
        raise Exception(f"pair-verify M4 error: {m4[TLV.kTLVType_Error].hex()}")

    # Derive encryption keys for the session
    session.encrypt_key = hkdf_derive(shared_secret, b"Control-Salt",
                                       b"Control-Write-Encryption-Key", 32)
    session.decrypt_key = hkdf_derive(shared_secret, b"Control-Salt",
                                       b"Control-Read-Encryption-Key", 32)
    session.send_counter = 0
    session.recv_counter = 0

    print(f"  Encrypted session established with {session.host}:{session.port}")


async def cmd_pair(host: str, port: int, code: str):
    session = HapSession(host, port)
    try:
        pairing = await pair_setup(session, code)
        key = f"{host}:{port}"
        pairings = load_pairings()
        pairings[key] = pairing
        save_pairings(pairings)
        print(f"\nPairing saved to {PAIRING_FILE}")
    finally:
        await session.close()


async def _get_session(host: str, port: int) -> HapSession:
    key = f"{host}:{port}"
    pairings = load_pairings()
    if key not in pairings:
        print(f"No pairing for {key}. Run 'pair' first.")
        sys.exit(1)

    session = HapSession(host, port)
    await pair_verify(session, pairings[key])
    return session


async def cmd_list(host: str, port: int):
    session = await _get_session(host, port)
    try:
        data = await session.encrypted_get_json("/accessories")
        accessories = data.get("accessories", [])

        for acc in accessories:
            aid = acc["aid"]
            print(f"\nAccessory {aid}:")
            for svc in acc.get("services", []):
                stype = svc.get("type", "?")
                print(f"\n  Service: {stype}")
                for char in svc.get("characteristics", []):
                    iid = char["iid"]
                    ctype = char.get("type", "?")
                    value = char.get("value")
                    perms = char.get("perms", [])
                    fmt = char.get("format", "?")
                    desc = char.get("description", "")
                    marker = ""
                    if "119" in ctype:
                        marker = " <<< VOLUME"
                    print(f"    [{aid}.{iid}] {ctype} = {value} ({fmt}, {perms}) {desc}{marker}")
    finally:
        await session.close()


async def cmd_get(host: str, port: int):
    session = await _get_session(host, port)
    try:
        data = await session.encrypted_get_json("/accessories")
        aid, iid = _find_volume(data)
        if aid is None:
            print("Volume characteristic not found!")
            return

        result = await session.encrypted_get_json(f"/characteristics?id={aid}.{iid}")
        chars = result.get("characteristics", [])
        if chars:
            print(f"Volume: {chars[0].get('value')}")
        else:
            print("No value returned")
    finally:
        await session.close()


async def cmd_set(host: str, port: int, value: int):
    session = await _get_session(host, port)
    try:
        data = await session.encrypted_get_json("/accessories")
        aid, iid = _find_volume(data)
        if aid is None:
            print("Volume characteristic not found!")
            return

        body = {"characteristics": [{"aid": aid, "iid": iid, "value": value}]}
        result = await session.encrypted_put_json("/characteristics", body)
        print(f"Volume set to {value}")
        if result:
            print(f"  Response: {result}")
    finally:
        await session.close()


def _find_volume(accessories_data):
    for acc in accessories_data.get("accessories", []):
        aid = acc["aid"]
        for svc in acc.get("services", []):
            for char in svc.get("characteristics", []):
                ctype = char.get("type", "")
                if "119" in ctype:
                    return aid, char["iid"]
                if "volume" in char.get("description", "").lower():
                    return aid, char["iid"]
    return None, None


def main():
    p = argparse.ArgumentParser(description="HAP volume control for AirPlay speakers")
    sub = p.add_subparsers(dest="cmd")

    pp = sub.add_parser("pair")
    pp.add_argument("--host", required=True)
    pp.add_argument("--port", type=int, required=True)
    pp.add_argument("--code", required=True, help="HAP setup code (XXX-XX-XXX)")

    for name in ("list", "get", "set"):
        sp = sub.add_parser(name)
        sp.add_argument("--host", required=True)
        sp.add_argument("--port", type=int, required=True)
        if name == "set":
            sp.add_argument("--value", type=int, required=True)

    args = p.parse_args()
    if args.cmd == "pair":
        asyncio.run(cmd_pair(args.host, args.port, args.code))
    elif args.cmd == "list":
        asyncio.run(cmd_list(args.host, args.port))
    elif args.cmd == "get":
        asyncio.run(cmd_get(args.host, args.port))
    elif args.cmd == "set":
        asyncio.run(cmd_set(args.host, args.port, args.value))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
