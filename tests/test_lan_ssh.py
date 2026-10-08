"""OpenSSH / sshfs of on-link RFC1918 hosts binds the home NIC, not the VPN."""
from __future__ import annotations

from types import SimpleNamespace

from app.tools.lan_ssh import (
    git_ssh_command,
    ssh_destination_host,
    ssh_host_from_token,
    with_lan_ssh_bind,
)


def _home_vpn_nics():
    import socket

    return {
        "eth0": [
            SimpleNamespace(family=socket.AF_INET, address="192.168.1.12", netmask="255.255.255.0"),
        ],
        "wg0": [
            SimpleNamespace(family=socket.AF_INET, address="10.8.0.2", netmask="255.255.255.0"),
        ],
    }


def test_ssh_host_from_token_user_and_scp_path():
    assert ssh_host_from_token("taco@192.168.1.1") == "192.168.1.1"
    assert ssh_host_from_token("git@192.168.1.40:repo.git") == "192.168.1.40"
    assert ssh_host_from_token("user@nas.local:/share") == "nas.local"
    assert ssh_destination_host(["ssh", "-p", "2222", "root@192.168.1.1", "uptime"]) == "192.168.1.1"
    assert ssh_destination_host(["scp", "file.txt", "taco@192.168.1.1:/tmp/"]) == "192.168.1.1"
    assert ssh_destination_host(["sshfs", "taco@192.168.1.50:/media", "/mnt/nas"]) == "192.168.1.50"
    assert ssh_destination_host(["ssh", "github.com"]) == ""


def test_with_lan_ssh_bind_pins_home_nic_not_vpn(monkeypatch):
    monkeypatch.setattr("psutil.net_if_addrs", _home_vpn_nics)
    lan = with_lan_ssh_bind(["/usr/bin/ssh", "taco@192.168.1.50"])
    assert lan[1:3] == ["-o", "BindAddress=192.168.1.12"]
    assert lan[-1] == "taco@192.168.1.50"
    scp = with_lan_ssh_bind(["/usr/bin/scp", "-P", "22", "a.txt", "user@192.168.1.1:/tmp/a.txt"])
    assert scp[1:3] == ["-o", "BindAddress=192.168.1.12"]
    public = with_lan_ssh_bind(["/usr/bin/ssh", "git@github.com"])
    assert public == ["/usr/bin/ssh", "git@github.com"]
    jumped = with_lan_ssh_bind(["/usr/bin/ssh", "-J", "bastion", "taco@192.168.1.1"])
    assert jumped[1] == "-J"
    already = with_lan_ssh_bind(["/usr/bin/ssh", "-o", "BindAddress=10.8.0.2", "taco@192.168.1.1"])
    assert already[2] == "BindAddress=10.8.0.2"
    mounted = with_lan_ssh_bind(["/usr/bin/sshfs", "taco@192.168.1.50:/media", "/mnt/nas"])
    assert mounted[1:3] == ["-o", "BindAddress=192.168.1.12"]
    assert mounted[-2:] == ["taco@192.168.1.50:/media", "/mnt/nas"]
    direct = with_lan_ssh_bind(
        ["/usr/bin/sshfs", "-o", "directport=22", "taco@192.168.1.50:/", "/mnt"]
    )
    assert direct[1:3] == ["-o", "directport=22"]


def test_git_ssh_command_points_at_this_module():
    cmd = git_ssh_command()
    assert "lan_ssh.py" in cmd
