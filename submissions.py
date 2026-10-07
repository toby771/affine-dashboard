from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

import bittensor as bt

from app.bittensor_service import MetagraphCache


AFFINE_DATA_URL = "https://affine.io/network-data.json"
CACHE_TTL_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 15


class SubmissionService:
    """Loads Affine epoch submission grids and maps current miner UIDs to coldkeys."""

    def __init__(
        self,
        netuid: int = 120,
        network: str = "finney",
        metagraph_cache: MetagraphCache | None = None,
    ):
        self.netuid = netuid
        self.network = network
        self.metagraph_cache = metagraph_cache or MetagraphCache()
        self._lock = threading.Lock()
        self._epochs: list[dict[str, Any]] | None = None
        self._epochs_cached_at = 0.0
        self._miners_by_coldkey: dict[str, list[dict[str, Any]]] | None = None
        self._miners_cached_at = 0.0

    def clear_cache(self) -> None:
        with self._lock:
            self._epochs = None
            self._epochs_cached_at = 0.0
            self._miners_by_coldkey = None
            self._miners_cached_at = 0.0

    def _load_epochs(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if (
            self._epochs is not None
            and now - self._epochs_cached_at < CACHE_TTL_SECONDS
        ):
            return self._epochs

        with self._lock:
            now = time.monotonic()
            if (
                self._epochs is not None
                and now - self._epochs_cached_at < CACHE_TTL_SECONDS
            ):
                return self._epochs

            request = Request(
                AFFINE_DATA_URL,
                headers={"User-Agent": "SN120-Manager/1.0"},
            )
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.load(response)

            summary = payload.get("summary", {})
            data_netuid = summary.get("netuid")
            if data_netuid is not None and int(data_netuid) != self.netuid:
                raise ValueError(
                    f"Submission endpoint returned netuid {data_netuid}; "
                    f"expected {self.netuid}."
                )

            epochs = payload.get("epochs")
            if not isinstance(epochs, list):
                raise ValueError(
                    "Submission endpoint response is missing the epochs list."
                )
            for index, epoch in enumerate(epochs):
                if not isinstance(epoch, dict) or not isinstance(
                    epoch.get("grid"), list
                ):
                    raise ValueError(
                        f"Submission epoch at index {index} has no UID grid."
                    )

            self._epochs = epochs
            self._epochs_cached_at = time.monotonic()
            return epochs

    def _load_miners(self) -> dict[str, list[dict[str, Any]]]:
        now = time.monotonic()
        if (
            self._miners_by_coldkey is not None
            and now - self._miners_cached_at < CACHE_TTL_SECONDS
        ):
            return self._miners_by_coldkey

        with self._lock:
            now = time.monotonic()
            if (
                self._miners_by_coldkey is not None
                and now - self._miners_cached_at < CACHE_TTL_SECONDS
            ):
                return self._miners_by_coldkey

            metagraph = self.metagraph_cache.get(self._fetch_metagraph)

            owner_hotkey = metagraph.owner_hotkey
            owner_coldkey = metagraph.owner_coldkey
            miners_by_coldkey: dict[str, list[dict[str, Any]]] = {}
            for neuron in metagraph:
                if (
                    neuron.validator_permit
                    or neuron.hotkey == owner_hotkey
                    or neuron.coldkey == owner_coldkey
                ):
                    continue
                miners_by_coldkey.setdefault(neuron.coldkey, []).append(
                    {
                        "uid": neuron.uid,
                        "hotkey": neuron.hotkey,
                    }
                )

            self._miners_by_coldkey = miners_by_coldkey
            self._miners_cached_at = time.monotonic()
            return miners_by_coldkey

    def _fetch_metagraph(self) -> Any:
        with bt.Subtensor(network=self.network) as subtensor:
            metagraph = subtensor.subnets.metagraph(netuid=self.netuid)
            if metagraph is None:
                raise RuntimeError(
                    f"No metagraph found for netuid {self.netuid} "
                    f"on network {self.network}."
                )
            return metagraph

    def history(self, selected_coldkeys: list[str]) -> dict[str, Any]:
        epochs = self._load_epochs()
        miners_by_coldkey = self._load_miners()
        unknown = set(selected_coldkeys) - miners_by_coldkey.keys()
        if unknown:
            raise ValueError(
                "Selected coldkey is not present in the current miner registry."
            )

        coldkeys = [
            {
                "coldkey": coldkey,
                "miner_count": len(miners),
            }
            for coldkey, miners in miners_by_coldkey.items()
        ]
        coldkeys.sort(key=lambda item: (-item["miner_count"], item["coldkey"]))

        series = []
        for coldkey in selected_coldkeys:
            for miner in miners_by_coldkey[coldkey]:
                points = []
                for epoch in epochs:
                    grid = epoch["grid"]
                    uid = miner["uid"]
                    submission_count = (
                        int(grid[uid]) if uid < len(grid) else 0
                    )
                    epoch_id = str(epoch.get("id", ""))
                    label = epoch_id.rsplit("-", 1)[-1] or epoch_id
                    points.append(
                        {
                            "label": label,
                            "start": int(epoch.get("start", 0)),
                            "submission_count": submission_count,
                        }
                    )
                points.sort(key=lambda point: point["start"])
                series.append(
                    {
                        "coldkey": coldkey,
                        "uid": miner["uid"],
                        "hotkey": miner["hotkey"],
                        "points": points,
                    }
                )

        return {
            "netuid": self.netuid,
            "coldkeys": coldkeys,
            "selected_coldkeys": selected_coldkeys,
            "selected_miner_count": len(series),
            "epochs_count": len(epochs),
            "series": series,
            "updated_at": time.time(),
        }
