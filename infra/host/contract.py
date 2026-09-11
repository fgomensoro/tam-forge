"""What the host must be before anything is written to it.

The contract is a flat env file with no secrets: release, architecture, approved name and
address, the ports that may be open, the identities that run services, and the memory each
service may use. It is parsed strictly and cross-checked here, so a typo in a port list or
a budget that no longer fits the machine fails before a script reaches the host, not after.

The two rules that matter most are stated as code. Nothing runs as root: every service user
is listed and root is not one of them. And the memory budgets plus a safety reserve for
PostgreSQL, Caddy and the operating system must fit inside the host's RAM, so the CX23
cannot be oversubscribed by adding one more worker to the list.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

APPROVED_RELEASE: Final = "24.04"
APPROVED_ARCH: Final = "x86_64"
FORBIDDEN_HOSTS: Final[frozenset[str]] = frozenset({"lamas-prod", "lamas", "n8n-prod-gastos"})
REQUIRED_PUBLIC_PORTS: Final[frozenset[int]] = frozenset({22, 80, 443})
SERVICES: Final[tuple[str, ...]] = ("api", "worker", "speech", "claude", "embedding")


class ContractError(ValueError):
    """The host contract is inconsistent; nothing may run against the host."""


@dataclass(frozen=True, slots=True)
class HostContract:
    release: str
    arch: str
    host_name: str
    host_ip: str
    provider_id: str
    app_hostname: str
    ssh_source_cidr: str
    public_ports: tuple[int, ...]
    loopback_ports: tuple[int, ...]
    ram_mb: int
    safety_reserve_mb: int
    packages: dict[str, str]
    service_users: tuple[str, ...]
    shared_group: str
    budgets_mb: dict[str, int]
    releases_dir: str
    current_link: str
    config_dir: str
    state_dir: str
    cache_dir: str

    @property
    def budget_total_mb(self) -> int:
        return sum(self.budgets_mb.values())

    def validate(self) -> None:
        if self.release != APPROVED_RELEASE:
            raise ContractError(f"only Ubuntu {APPROVED_RELEASE} is approved")
        if self.arch != APPROVED_ARCH:
            raise ContractError(f"only {APPROVED_ARCH} is approved")
        if self.host_name in FORBIDDEN_HOSTS or self.provider_id.startswith("lamas"):
            raise ContractError("the contract names a host that must never be provisioned")
        ipaddress.ip_address(self.host_ip)
        ipaddress.ip_network(self.ssh_source_cidr)
        if set(self.public_ports) != REQUIRED_PUBLIC_PORTS:
            raise ContractError("public ports are exactly SSH, HTTP and HTTPS")
        if set(self.public_ports) & set(self.loopback_ports):
            raise ContractError("a loopback port cannot also be public")
        if "root" in self.service_users or any(
            not u.startswith("tamforge-") for u in self.service_users
        ):
            raise ContractError("services run as tamforge-* users, never root")
        for service in SERVICES:
            if service not in self.budgets_mb or self.budgets_mb[service] <= 0:
                raise ContractError(f"{service} has no positive memory budget")
        if self.budget_total_mb + self.safety_reserve_mb > self.ram_mb:
            raise ContractError(
                f"budgets ({self.budget_total_mb} MB) plus reserve ({self.safety_reserve_mb} MB)"
                f" exceed host RAM ({self.ram_mb} MB)"
            )
        if self.safety_reserve_mb < 512:
            raise ContractError("the PostgreSQL, Caddy and OS reserve is at least 512 MB")
        for path in (
            self.releases_dir,
            self.current_link,
            self.config_dir,
            self.state_dir,
            self.cache_dir,
        ):
            if not path.startswith("/") or ".." in path:
                raise ContractError(f"{path!r} is not an absolute, normal path")


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ContractError(f"malformed line: {line!r}")
        key, value = line.split("=", 1)
        if not key.startswith("TAMFORGE_"):
            raise ContractError(f"unexpected key {key!r}")
        values[key.strip()] = value.strip()
    return values


def load_contract(path: Path) -> HostContract:
    values = parse_env(path.read_text(encoding="utf-8"))
    try:
        contract = HostContract(
            release=values["TAMFORGE_HOST_RELEASE"],
            arch=values["TAMFORGE_HOST_ARCH"],
            host_name=values["TAMFORGE_HOST_NAME"],
            host_ip=values["TAMFORGE_HOST_IP"],
            provider_id=values["TAMFORGE_HOST_PROVIDER_ID"],
            app_hostname=values["TAMFORGE_APP_HOSTNAME"],
            ssh_source_cidr=values["TAMFORGE_SSH_SOURCE_CIDR"],
            public_ports=tuple(int(p) for p in values["TAMFORGE_PUBLIC_PORTS"].split(",")),
            loopback_ports=tuple(int(p) for p in values["TAMFORGE_LOOPBACK_PORTS"].split(",")),
            ram_mb=int(values["TAMFORGE_HOST_RAM_MB"]),
            safety_reserve_mb=int(values["TAMFORGE_SAFETY_RESERVE_MB"]),
            packages={
                "postgresql": values["TAMFORGE_PKG_POSTGRESQL"],
                "pgvector": values["TAMFORGE_PKG_PGVECTOR"],
                "caddy": values["TAMFORGE_PKG_CADDY"],
                "ufw": values["TAMFORGE_PKG_UFW"],
            },
            service_users=tuple(values["TAMFORGE_SERVICE_USERS"].split(",")),
            shared_group=values["TAMFORGE_SHARED_GROUP"],
            budgets_mb={s: int(values[f"TAMFORGE_BUDGET_{s.upper()}_MB"]) for s in SERVICES},
            releases_dir=values["TAMFORGE_RELEASES_DIR"],
            current_link=values["TAMFORGE_CURRENT_LINK"],
            config_dir=values["TAMFORGE_CONFIG_DIR"],
            state_dir=values["TAMFORGE_STATE_DIR"],
            cache_dir=values["TAMFORGE_CACHE_DIR"],
        )
    except KeyError as missing:
        raise ContractError(f"contract is missing {missing}") from None
    except ValueError as error:
        raise ContractError(str(error)) from None
    contract.validate()
    return contract


__all__ = [
    "APPROVED_ARCH",
    "APPROVED_RELEASE",
    "ContractError",
    "HostContract",
    "SERVICES",
    "load_contract",
    "parse_env",
]
