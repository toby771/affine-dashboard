from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Any

import bittensor as bt


RAO_PER_TOKEN = 1_000_000_000


@dataclass
class Miner:
    uid: int
    hotkey: str
    coldkey: str
    active: bool
    validator_permit: bool
    projected_tao_per_day: float
    incentive: float
    rank: float
    trust: float
    consensus: float
    stake_tao: float
    last_update: int

    @property
    def is_miner(self) -> bool:
        return not self.validator_permit

    @property
    def short_hotkey(self) -> str:
        return f"{self.hotkey[:8]}…{self.hotkey[-6:]}"

    @property
    def short_coldkey(self) -> str:
        return f"{self.coldkey[:8]}…{self.coldkey[-6:]}"

    def to_dict(self):
        data = asdict(self)
        data["is_miner"] = self.is_miner
        data["short_hotkey"] = self.short_hotkey
        data["short_coldkey"] = self.short_coldkey
        return data


@dataclass
class ColdkeySummary:
    coldkey: str
    total_hotkeys: int
    active_hotkeys: int
    miner_hotkeys: int
    active_miners: int
    projected_tao_per_day: float
    miners: list[dict[str, Any]]

    @property
    def short_coldkey(self) -> str:
        return f"{self.coldkey[:8]}…{self.coldkey[-6:]}"

    def to_dict(self):
        data = asdict(self)
        data["short_coldkey"] = self.short_coldkey
        return data


class Subnet120Manager:
    """
    Reads the subnet metagraph and builds a coldkey -> hotkeys/miners
    management view.

    The Bittensor connection is deliberately kept here instead of in Flask
    routes, so future management functions can be added without mixing
    blockchain logic with HTTP/UI code.
    """

    def __init__(
        self,
        netuid: int = 120,
        network: str = "finney",
        cache_seconds: int = 30,
        blocks_per_day: int = 7200,
    ):
        self.netuid = netuid
        self.network = network
        self.cache_seconds = cache_seconds
        self.blocks_per_day = blocks_per_day

        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_time = 0.0

    @staticmethod
    def _number(value, default=0.0) -> float:
        try:
            if hasattr(value, "item"):
                value = value.item()
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _int(value, default=0) -> int:
        try:
            if hasattr(value, "item"):
                value = value.item()
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @classmethod
    def _tao_amount(cls, value) -> float:
        if hasattr(value, "rao"):
            return cls._int(value.rao) / RAO_PER_TOKEN
        return cls._number(value)

    def _sync_metagraph(self):
        """
        Load the subnet metagraph with a fresh, scoped RPC connection.

        Prefer the current typed Subtensor API, with a fallback for older SDKs.
        """
        with bt.Subtensor(network=self.network) as sub:
            subnets = getattr(sub, "subnets", None)
            fetch_metagraph = getattr(subnets, "metagraph", None)
            if callable(fetch_metagraph):
                metagraph = fetch_metagraph(netuid=self.netuid)
                if metagraph is None:
                    raise RuntimeError(
                        f"No metagraph found for netuid {self.netuid} "
                        f"on network {self.network}."
                    )
                return metagraph

            metagraph_factory = getattr(bt, "metagraph", None)
            if callable(metagraph_factory):
                metagraph = metagraph_factory(
                    netuid=self.netuid,
                    network=self.network,
                )
                metagraph.sync(subtensor=sub)
                return metagraph

            raise RuntimeError(
                "The installed Bittensor SDK does not expose a supported "
                "metagraph API."
            )

    def _build_snapshot(self) -> dict[str, Any]:
        mg = self._sync_metagraph()

        typed_neurons = getattr(mg, "neurons", None)
        if typed_neurons is not None:
            typed_neurons = list(typed_neurons)
            uids = [neuron.uid for neuron in typed_neurons]
            hotkeys = [neuron.hotkey for neuron in typed_neurons]
            coldkeys = [neuron.coldkey for neuron in typed_neurons]
            validator_permit = [
                neuron.validator_permit for neuron in typed_neurons
            ]
            emissions = [neuron.emission for neuron in typed_neurons]
            incentives = [neuron.incentive for neuron in typed_neurons]
            ranks = [neuron.rank for neuron in typed_neurons]
            trusts = [neuron.trust for neuron in typed_neurons]
            consensus = [neuron.consensus for neuron in typed_neurons]
            stake = [neuron.tao_stake for neuron in typed_neurons]
            last_update = [neuron.last_update for neuron in typed_neurons]
        else:
            uids = list(getattr(mg, "uids", []))
            hotkeys = list(getattr(mg, "hotkeys", []))
            coldkeys = list(getattr(mg, "coldkeys", []))
            validator_permit = list(getattr(mg, "validator_permit", []))
            emissions = list(
                getattr(mg, "emission", getattr(mg, "emissions", []))
            )
            incentives = list(getattr(mg, "I", getattr(mg, "incentive", [])))
            ranks = list(getattr(mg, "R", getattr(mg, "rank", [])))
            trusts = list(getattr(mg, "T", getattr(mg, "trust", [])))
            consensus = list(getattr(mg, "C", getattr(mg, "consensus", [])))
            stake = list(getattr(mg, "S", getattr(mg, "stake", [])))
            last_update = list(getattr(mg, "last_update", []))
        tao_per_alpha = self._number(getattr(mg, "price", None))
        if tao_per_alpha <= 0:
            tao_in = self._number(getattr(mg, "tao_in", None))
            alpha_in = self._number(getattr(mg, "alpha_in", None))
            if tao_in > 0 and alpha_in > 0:
                tao_per_alpha = tao_in / alpha_in
        if tao_per_alpha <= 0:
            raise RuntimeError(
                f"Subnet {self.netuid} has no usable TAO/alpha spot price; "
                "cannot convert miner emissions to TAO."
            )
        tempo = self._int(getattr(mg, "tempo", 0))
        if tempo <= 0:
            raise RuntimeError(
                f"Subnet {self.netuid} did not return a valid tempo; "
                "cannot project epoch emissions to a daily amount."
            )
        epochs_per_day = self.blocks_per_day / tempo

        n = self._int(
            getattr(
                mg,
                "n",
                getattr(mg, "num_uids", len(typed_neurons or uids)),
            )
        )

        count = min(
            n,
            len(uids),
            len(hotkeys),
            len(coldkeys),
        )

        miners: list[Miner] = []

        for i in range(count):
            uid = self._int(uids[i], i)
            hk = str(hotkeys[i])
            ck = str(coldkeys[i])

            has_validator_permit = (
                bool(validator_permit[i])
                if i < len(validator_permit)
                else False
            )

            # A subnet slot is treated as a miner when it does not have a
            # validator permit.
            is_miner = not has_validator_permit
            if not is_miner:
                continue

            raw_emission = emissions[i] if i < len(emissions) else 0
            emission_alpha_per_epoch = (
                self._int(getattr(raw_emission, "rao", raw_emission))
                / RAO_PER_TOKEN
            )
            projected_tao = (
                emission_alpha_per_epoch * tao_per_alpha * epochs_per_day
            )

            miner = Miner(
                uid=uid,
                hotkey=hk,
                coldkey=ck,
                active=projected_tao > 0,
                validator_permit=has_validator_permit,
                projected_tao_per_day=projected_tao,
                incentive=self._number(incentives[i]) if i < len(incentives) else 0.0,
                rank=self._number(ranks[i]) if i < len(ranks) else 0.0,
                trust=self._number(trusts[i]) if i < len(trusts) else 0.0,
                consensus=self._number(consensus[i]) if i < len(consensus) else 0.0,
                stake_tao=self._tao_amount(stake[i]) if i < len(stake) else 0.0,
                last_update=self._int(last_update[i]) if i < len(last_update) else 0,
            )
            miners.append(miner)

        groups: dict[str, list[Miner]] = defaultdict(list)
        for miner in miners:
            groups[miner.coldkey].append(miner)

        coldkeys_summary: list[ColdkeySummary] = []

        for coldkey, group in groups.items():
            active_miners = [m for m in group if m.active]

            coldkeys_summary.append(
                ColdkeySummary(
                    coldkey=coldkey,
                    total_hotkeys=len(group),
                    active_hotkeys=sum(1 for m in group if m.active),
                    miner_hotkeys=len(group),
                    active_miners=len(active_miners),
                    projected_tao_per_day=sum(
                        m.projected_tao_per_day for m in group
                    ),
                    miners=[m.to_dict() for m in group],
                )
            )

        coldkeys_summary.sort(
            key=lambda x: x.projected_tao_per_day,
            reverse=True,
        )

        active_miners = [m for m in miners if m.active]
        projected_tao_per_day = sum(m.projected_tao_per_day for m in miners)
        active_projected_tao_per_day = sum(
            m.projected_tao_per_day for m in active_miners
        )

        block = self._int(getattr(mg, "block", 0))

        return {
            "netuid": self.netuid,
            "network": self.network,
            "block": block,
            "tempo": tempo,
            "epochs_per_day": epochs_per_day,
            "alpha_price_tao": tao_per_alpha,
            "neuron_count": count,
            "miner_count": len(miners),
            "active_miner_count": len(active_miners),
            "coldkey_count": len(coldkeys_summary),
            "projected_tao_per_day": projected_tao_per_day,
            "active_projected_tao_per_day": active_projected_tao_per_day,
            "coldkeys": [c.to_dict() for c in coldkeys_summary],
            "miners": [m.to_dict() for m in sorted(
                miners,
                key=lambda x: x.projected_tao_per_day,
                reverse=True,
            )],
            "updated_at": time.time(),
        }

    def snapshot(self, force: bool = False) -> dict[str, Any]:
        now = time.time()

        if (
            not force
            and self._cache is not None
            and now - self._cache_time < self.cache_seconds
        ):
            return self._cache

        with self._lock:
            now = time.time()
            if (
                not force
                and self._cache is not None
                and now - self._cache_time < self.cache_seconds
            ):
                return self._cache

            snapshot = self._build_snapshot()
            self._cache = snapshot
            self._cache_time = time.time()
            return snapshot

    def get_coldkey(self, coldkey: str) -> dict[str, Any] | None:
        snapshot = self.snapshot()
        for item in snapshot["coldkeys"]:
            if item["coldkey"] == coldkey:
                return item
        return None
