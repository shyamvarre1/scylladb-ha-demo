# ScyllaDB HA Simulator

An interactive, single-file simulator of ScyllaDB's replication, consistency levels, and fault tolerance — built to make Replication Factor (RF) and Consistency Level (CL) tradeoffs visible rather than abstract.

Nodes are grouped into zones/racks; each client sends writes and reads that animate through a coordinator and the key's natural replicas, so you can watch RF/CL decide in real time whether a request succeeds. Click a node to take it down, or a zone/rack's border to take the whole zone/rack down together, and see how the cluster responds.

The simulator has **two consistency models**, switchable from the Consistency Model dropdown, so the same cluster and the same failures can be compared side by side.

**Disclaimer:** An independent, educational simulator — not an official ScyllaDB product and not 100% behaviorally accurate to real ScyllaDB internals. Not affiliated with or endorsed by ScyllaDB, Inc.

![Simulator demo](docs/simulator-demo.gif)

## Consistency models

**Eventual (RF/CL)** — the classic Cassandra/Scylla coordinator path. Every replica accepts writes directly, and the Consistency Level decides how many acknowledgements a request waits for before answering the client. A coordinator fails fast with `UNAVAILABLE` when too few replicas are live to meet CL, and otherwise replies the instant CL is satisfied without waiting for the stragglers.

**Strong (Raft)** — each key's natural replicas form their own Raft group, the way tablets use Raft rather than the way cluster-wide group 0 does. There is no CL to tune: a group of RF members always commits on a majority of itself.

- **Leader election.** A group with no live leader runs a pre-vote round, then bumps the term and runs a real election. Both rounds need a majority. The group is genuinely unavailable while this happens — kill the leader and watch the next request stall through an election before it can be served.
- **Majority commit.** The leader appends the entry to the group log and replicates it with AppendEntries. It commits — and only then answers the client — once a majority of members have persisted it. A write that can't reach a majority stays in the leader's log, uncommitted and unacknowledged.
- **Leader forwarding.** A client that lands on a non-leader gets `not_a_leader` and the request is forwarded, so the cost of landing off-leader is visible as an extra hop. Turn on Smart Drivers and the entry point often *is* a group member, sometimes the leader itself.
- **Read barriers.** A linearizable read is not served from the leader's local copy. The leader first confirms with a majority that it still leads the current term, and only then answers. Kill enough members and a read is refused even though the leader is up and holding the value — it can't prove it is still the leader, so it won't risk a stale answer. That refusal is the sharpest contrast with `CL=ONE`.

The behavior follows [scylladb/scylladb](https://github.com/scylladb/scylladb)'s `raft/` library: pre-vote elections carrying a term (`fsm::become_candidate`), majority commit (`tracker::committed`, quorum = `size / 2 + 1`), commands forwarded to the leader (`raft/server.cc`, `not_a_leader`), and read barriers (`fsm::start_read_barrier` / `broadcast_read_quorum`).

## Features

- Two consistency models — eventual (RF/CL) and strong (per-key Raft groups) — over the same cluster
- Adjustable nodes, zones/racks, replication factor, consistency level, and client count
- Per-client Write / Read buttons — requests visibly originate from a specific client
- Zone/rack-aware replica placement, with click-to-kill/revive on both individual nodes and whole zones/racks
- A "Smart Drivers" toggle to compare token-aware routing against a non-token-aware proxy hop
- Per-key Raft group and leader (`L·t<term>`) drawn on the stage, tracking the selected key
- A first-visit guided tour of the core interactions
- Styled with the ScyllaDB design system

## Running it

This is a static, dependency-free single HTML file. Clone the repo and open `index.html` in a browser — no build step, no server required.

```bash
git clone https://github.com/<you>/scylladb-ha-demo.git
cd scylladb-ha-demo
open index.html   # or just double-click it / drag into a browser
```
