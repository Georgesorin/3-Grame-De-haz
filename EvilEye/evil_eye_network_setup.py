from __future__ import annotations

import ipaddress
import random
import socket
import time
from typing import Any

from Controller import calc_checksum_send, load_config, save_config


def build_discovery_packet():
    rand1, rand2 = random.randint(0, 127), random.randint(0, 127)
    payload = bytearray(
        [0x0A, 0x02, *b"KX-HC04", 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14]
    )
    pkt = bytearray([0x67, rand1, rand2, len(payload)]) + payload
    pkt.append(calc_checksum_send(pkt))
    return pkt, rand1, rand2


def _ipv4_from_string(addr: str) -> ipaddress.IPv4Address | None:
    if not addr or "%" in addr:
        return None
    try:
        return ipaddress.IPv4Address(addr.strip())
    except ValueError:
        return None


def _broadcast_for_ip_netmask(ip: str, netmask: str) -> str:
    if not netmask:
        return "255.255.255.255"
    try:
        if_net = ipaddress.IPv4Interface(f"{ip}/{netmask}")
        return str(if_net.network.broadcast_address)
    except (ValueError, OSError):
        return "255.255.255.255"


def _interfaces_from_psutil():
    try:
        import psutil
    except ImportError:
        return []

    out = []
    seen = set()
    # Compare int(family) — on some Windows builds family may not be identical to socket.AF_INET
    af_inet = int(socket.AF_INET)
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if int(addr.family) != af_inet:
                continue
            ip = addr.address
            ipa = _ipv4_from_string(ip)
            if ipa is None or ipa.is_loopback or str(ipa) == "0.0.0.0":
                continue
            ip_s = str(ipa)
            if ip_s in seen:
                continue
            netmask = (addr.netmask or "").strip()
            bcast = _broadcast_for_ip_netmask(ip_s, netmask)
            out.append((iface, ip_s, bcast))
            seen.add(ip_s)
    return out


def _default_route_ipv4() -> str | None:
    """Local IPv4 chosen for default route (no traffic leaves the machine)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _interfaces_from_hostname() -> list[tuple[str, str, str]]:
    out = []
    seen = set()
    try:
        _, _, ip_list = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        return []
    for ip in ip_list:
        ipa = _ipv4_from_string(ip)
        if ipa is None or ipa.is_loopback:
            continue
        ip_s = str(ipa)
        if ip_s in seen:
            continue
        out.append((f"hostname:{socket.gethostname()}", ip_s, "255.255.255.255"))
        seen.add(ip_s)
    return out


def get_local_interfaces():
    """
    Return [(iface_name, host_ip, broadcast_ip), ...] for non-loopback IPv4.

    Uses psutil when available; falls back to default-route and hostname resolution
    so a missing/empty psutil view (common in minimal venvs) still yields choices.
    """
    out = _interfaces_from_psutil()
    seen = {t[1] for t in out}

    dr = _default_route_ipv4()
    if dr:
        ipa = _ipv4_from_string(dr)
        if ipa and not ipa.is_loopback and dr not in seen:
            out.append(("default route", dr, "255.255.255.255"))
            seen.add(dr)

    for row in _interfaces_from_hostname():
        if row[1] not in seen:
            out.append(row)
            seen.add(row[1])

    # Listen on all NICs; discovery will probe each concrete subnet when this is chosen
    out.append(
        (
            "0.0.0.0 (all interfaces — scans each adapter above)",
            "0.0.0.0",
            "255.255.255.255",
        )
    )
    return out


def _probe_subnet(host_ip: str, bcast: str, listen_sec: float) -> list[dict[str, str]]:
    """Send one discovery on (bcast, 4626), listen listen_sec for matching replies."""
    pkt, r1, r2 = build_discovery_packet()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    devices: list[dict[str, str]] = []
    try:
        try:
            sock.bind((host_ip, 7800))
        except OSError:
            pass
        try:
            sock.sendto(pkt, (bcast, 4626))
        except OSError:
            return devices

        sock.settimeout(0.5)
        end = time.time() + listen_sec
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 30 and data[0] == 0x68 and data[1] == r1 and data[2] == r2:
                    if addr[0] not in [d["ip"] for d in devices]:
                        model = data[6:13].decode(errors="ignore").strip("\x00")
                        devices.append({"ip": addr[0], "model": model})
                        print(f"    Found {model} at {addr[0]}")
            except socket.timeout:
                continue
            except OSError:
                break
    finally:
        sock.close()
    return devices


def _merge_devices_unique(found: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for d in found:
        ip = d["ip"]
        if ip not in seen:
            seen.add(ip)
            out.append(d)
    return out


def run_discovery_flow() -> dict[str, Any]:
    """
    Console: pick interface, broadcast discovery, listen for replies.

    Returns:
        {"device_ip": str | None, "bind_ip": str, "iface": str}.
    """
    interfaces = get_local_interfaces()

    print("\n--- Network Selection ---")
    print("Choose the network where the Evil Eye receiver is connected")
    print("(e.g. Ethernet with 169.254.x.x before starting the game).")
    print(
        "Tip: 'all interfaces' scans every adapter below — a single global broadcast "
        "often misses hardware on another NIC.\n"
    )
    for i, (iface, ip, bcast) in enumerate(interfaces):
        print(f"[{i}] {iface} - {ip}")
    try:
        choice = int(input("\nSelect interface number: "))
        sel = interfaces[choice]
    except (ValueError, IndexError):
        sel = interfaces[0]
        print("Invalid choice, defaulting to [0].")
    iface_name, host_ip, bcast = sel
    print(f"Using {iface_name} ({host_ip})")

    devices: list[dict[str, str]] = []

    if host_ip == "0.0.0.0":
        concrete = [r for r in interfaces if r[1] != "0.0.0.0"]
        print("Scanning each adapter (one subnet at a time)...")
        per = 2.0
        for iname, hip, bc in concrete:
            print(f"  {iname} ({hip}) ...")
            devices.extend(_probe_subnet(hip, bc, per))
        devices = _merge_devices_unique(devices)
        if not devices:
            print("  Fallback: 0.0.0.0 -> 255.255.255.255 ...")
            devices = _probe_subnet("0.0.0.0", "255.255.255.255", 3.0)
    else:
        print("Listening for devices...")
        devices = _probe_subnet(host_ip, bcast, 3.0)

    if devices:
        print(f"Targeting {devices[0]['ip']}\n")
        return {
            "device_ip": devices[0]["ip"],
            "bind_ip": host_ip,
            "iface": iface_name,
        }
    print("No devices found; bind IP saved for this interface, device IP unchanged.\n")
    return {"device_ip": None, "bind_ip": host_ip, "iface": iface_name}


def persist_discovery_result(result: dict[str, Any] | None) -> None:
    if not result:
        return
    cfg = load_config()
    if result.get("device_ip"):
        cfg["device_ip"] = result["device_ip"]
    cfg["virtual_iface_ip"] = result.get("bind_ip", "0.0.0.0")
    save_config(cfg)


def run_startup_discovery_and_save_config() -> None:
    """Run console discovery and write eye_ctrl_config.json."""
    r = run_discovery_flow()
    persist_discovery_result(r)
