# ScyllaDB HA Simulator

An interactive, single-file simulator of ScyllaDB's replication, consistency levels, and fault tolerance — built to make Replication Factor (RF) and Consistency Level (CL) tradeoffs visible rather than abstract.

Nodes are grouped into zones/racks inside one or two datacenters; each client sends writes and reads that animate through a coordinator and the key's natural replicas, so you can watch RF/CL decide in real time whether a request succeeds. Click a node to take it down, or a zone/rack's or datacenter's border to take that whole failure domain down together, and see how the cluster responds.

**Disclaimer:** An independent, educational simulator — not an official ScyllaDB product and not 100% behaviorally accurate to real ScyllaDB internals. Not affiliated with or endorsed by ScyllaDB, Inc.

![Simulator demo](docs/simulator-demo.gif)

## Features

- Adjustable nodes, zones/racks, replication factor, consistency level, and client count
- **Multi-DC mode** — split the cluster into 2 datacenters, each with its own zones/racks, nodes, and **independent replication factor** (NetworkTopologyStrategy-style)
- Full consistency-level set: `ANY`, `ONE`, `QUORUM`, `ALL`, `LOCAL_ONE`, `LOCAL_QUORUM`, `EACH_QUORUM`
- Per-client Write / Read buttons — requests visibly originate from a specific client
- Per-client **local datacenter** badge, driving `LOCAL_*` scope and DC-aware coordinator routing
- **Step Mode** — pause each request at every hop and advance it manually, one step at a time
- Zone/rack-aware replica placement, with click-to-kill/revive on individual nodes, whole zones/racks, and whole datacenters
- A "Smart Drivers" toggle to compare token-aware routing against a non-token-aware proxy hop
- A first-visit guided tour of the core interactions
- Styled with the ScyllaDB design system

## Multi-datacenter and consistency levels

Turn on **Multi-DC (2 DCs)** and the cluster splits into two independent datacenters. Each gets its own RF slider, because `NetworkTopologyStrategy` takes a separate replication factor per DC — `{'DC0': 3, 'DC1': 3}` is just the common case, not a requirement.

| CL | Replicas contacted | Acks required |
| --- | --- | --- |
| `ONE` / `QUORUM` / `ALL` | every DC | 1 / majority / all, counted cluster-wide across the summed RF |
| `LOCAL_ONE` / `LOCAL_QUORUM` | the coordinator's DC only | 1 / majority of *that DC's* RF |
| `EACH_QUORUM` | every DC | a majority in **every** DC, independently |
| `ANY` | every DC | 1, falling back to a hinted handoff stored at the coordinator |

Two behaviors worth calling out, both verified against a real two-datacenter ScyllaDB 6.2 cluster driven by the Python driver — see [`verify/`](verify/) to reproduce:

- **`ANY` and `EACH_QUORUM` are write-only.** Reading at either level is rejected by the coordinator with `InvalidRequest code=2200 "<CL> ConsistencyLevel is only supported for writes"`, and the simulator reproduces that rejection rather than inventing a result.
- **"Local" means the coordinator's datacenter, not the client's.** With the client's DC fully stopped and the coordinator pinned to the surviving DC, `LOCAL_QUORUM` and `LOCAL_ONE` still succeed against the coordinator's own DC. In practice a DC-aware driver policy keeps the coordinator inside the client's local DC, so the simulator reports `NoHostAvailable` when that DC has no live node — modern drivers do not fail over to remote datacenters by default.

## Step Mode

Step Mode turns a request into a hop-by-hop walkthrough. Each write or read pauses three times — client → coordinator, coordinator → replicas fan-out, and coordinator → client reply — and the "Next Step ▶" button advances it while the "Current Step" readout and the event log describe exactly what is about to happen.

Because there is only one Next Step button, a stepped request holds a lock for its lifetime: the other clients' buttons are disabled until it finishes, and clicking one logs why. Turn Step Mode off mid-request and it simply runs to completion on its own.

## Known simplifications

- Each datacenter is modelled as its own token ring rather than one global ring with both DCs' nodes interleaved, so with symmetric DCs the per-DC replica sets line up index-for-index. Real placement would not be so tidy.
- Latency, hinted handoff, read repair, and LWT/`SERIAL` levels are either simplified or absent.
- Changing any topology control rebuilds the cluster, which clears stored keys and values.

## Running it

This is a static, dependency-free single HTML file. Clone the repo and open `index.html` in a browser — no build step, no server required.

```bash
git clone https://github.com/<you>/scylladb-ha-demo.git
cd scylladb-ha-demo
open index.html   # or just double-click it / drag into a browser
```
