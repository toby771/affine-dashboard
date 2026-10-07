# SN120 Manager

Flask/Jinja dashboard for managing and monitoring Bittensor subnet 120.

## What it does

The first version:

1. Creates a Bittensor `Subtensor` connection.
2. Loads the SN120 metagraph.
3. Reads the registered hotkeys and coldkeys.
4. Identifies miner slots as neurons without a validator permit.
5. Identifies active miners as miners with projected TAO/day greater than zero.
6. Groups miner hotkeys by coldkey.
7. Converts subnet-alpha emission to TAO and sums it for every coldkey.
8. Shows:
   - total miner hotkeys
   - active miners
   - projected miner income in τ/day
   - individual hotkey information
9. Provides JSON endpoints for future automation.

## Important income note

Bittensor's typed metagraph `emission` value is denominated in alpha and is
the allocation for the most recent subnet epoch—not an amount to multiply by
every block in a day. The dashboard converts that epoch allocation to TAO
using the current TAO-per-alpha spot price, then scales by the number of
epochs per day (`BLOCKS_PER_DAY / tempo`).

This project therefore reports:

- `Projected τ/day`: alpha emission per epoch × current TAO-per-alpha spot price × (`BLOCKS_PER_DAY / tempo`).
- `Active miner`: a miner whose projected TAO/day is greater than zero.

The dashboard also shows the fetched alpha spot price in TAO. For example, a
price of `0.046528 τ` per alpha means each alpha of emission is valued at
`0.046528 τ`. A USD quote such as `$13.902181` is not used for the TAO/day
calculation. Emission-per-block is not shown; tables report only the projected
daily TAO amount. The dashboard refreshes every 120 seconds by default. All
pages share one cached metagraph, refreshed at most once per 120 seconds, so
dashboard, coldkey, and submissions views do not each open their own RPC
connection.
The on-chain per-miner emission allocation itself updates when the subnet
completes its next epoch, so this is a projection based on the latest epoch,
not a real-time payout stream.

`python-dotenv` loads `.env` for direct `python app.py` and Gunicorn starts.
`METAGRAPH_CACHE_SECONDS` controls the shared metagraph cache (default 120);
`METAGRAPH_RETRY_SECONDS` prevents retrying a failed RPC connection more often
than every 90 seconds. If a refresh fails after a metagraph has been loaded,
the app logs the error and serves the last cached metagraph until the next
retry window.

If you later want **actual realized income over time**, add a database and record snapshots/chain events. Do not treat the dashboard projection as historical payout accounting.

## Project layout

```text
sn120_manager/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
└── app/
    ├── __init__.py
    ├── config.py
    ├── bittensor_service.py
    ├── routes.py
    ├── template_filters.py
    ├── templates/
    │   ├── base.html
    │   ├── dashboard.html
    │   └── coldkey.html
    └── static/
        └── app.css
```

## Install

Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy environment configuration:

```bash
cp .env.example .env
```

Then run:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Network

The default configuration is:

```text
NETUID=120
BT_NETWORK=finney
```

The service connects to the configured network and fetches the subnet through
the current typed SDK API:

```python
import bittensor as bt

with bt.Subtensor(network="finney") as sub:
    metagraph = sub.subnets.metagraph(netuid=120)
```

Older SDKs that do not expose `sub.subnets.metagraph` use the legacy
`bt.metagraph(...).sync(subtensor=...)` path.

The dashboard opens a scoped RPC connection for each uncached refresh and
closes it after the metagraph has been loaded.

## API

### Complete snapshot

```text
GET /api/snapshot
```

Force a fresh chain read:

```text
GET /api/snapshot?refresh=1
```

### Coldkey summaries

```text
GET /api/coldkeys
```

### Miner submissions by epoch

Open `/submissions`, filter the coldkey list, select one or more coldkeys, and
choose **Show chart**. The page starts with one stacked batch bar per epoch for
the latest 20 epochs: learner-eligible submissions (`learner_eligible`) and
learner-excluded submissions (`learner_excluded`) form a stacked bar, while a
separate bar shows miner submissions (`submissions`). Values are labeled on
the bars and the batch total (`batches`) appears above its stacked bar. Hover
over either bar to see the epoch and all four exact counts. For each selected
coldkey, the page uses the current
metagraph to get every miner's UID and hotkey, then renders a separate plot for
each miner. Each plot shows that miner's integer `epochs[].grid[uid]` count,
with one vertically stacked circle per submission and no count labels or lines
connecting epochs. Each chart shows only the latest 30 epochs and labels every
epoch in that window. Charts omit the unused count axis, and submission circles
are slightly larger for visibility. The page refreshes at the dashboard
refresh interval.

Because the supplied data provides UID grids while miner ownership comes from
the current metagraph, historical points use the current coldkey-to-UID mapping.
If a UID was deregistered or reassigned, older points may not represent the
historical owner.

### One coldkey

```text
GET /api/coldkey/<coldkey>
```

### Force refresh

```text
POST /api/refresh
```

## Production

For a simple production deployment:

```bash
gunicorn -w 1 -b 0.0.0.0:5000 app:app
```

Use one Gunicorn worker with the in-process RPC cache. Multiple workers have
separate caches and can independently exceed an endpoint's WebSocket limit.

Do not expose wallet/coldkey secrets to this application. The dashboard only needs public chain state for the functionality implemented here.

## Next recommended components

For a real SN120 management system, the next layer should be:

- SQLite/PostgreSQL historical snapshots
- coldkey/hotkey ownership history
- daily/weekly/monthly realized emission history
- miner uptime history
- alerts for inactive miners
- validator/miner classification rules specific to SN120
- CSV export
- authentication
- role-based management actions
- background sync worker instead of doing chain reads during HTTP requests
