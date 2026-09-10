# Verifying the simulator's consistency-level semantics

The simulator makes some non-obvious claims about how ScyllaDB behaves across datacenters. This
folder reproduces them against a real two-datacenter cluster so they can be re-checked rather than
taken on trust.

What it verifies:

| Claim | Result |
| --- | --- |
| `NetworkTopologyStrategy` takes an independent RF per DC | stored replication is `{'DC1': '1', 'DC2': '1'}` |
| `ANY` reads are rejected | `InvalidRequest code=2200 "ANY ConsistencyLevel is only supported for writes"` |
| `EACH_QUORUM` reads are rejected | `InvalidRequest code=2200 "EACH_QUORUM ConsistencyLevel is only supported for writes"` |
| `LOCAL_*` is scoped to the **coordinator's** DC | with DC1 stopped and the coordinator in DC2, `LOCAL_QUORUM` and `LOCAL_ONE` still succeed |
| control: cluster-wide `QUORUM` needs both DCs | fails with `"Requires 2, alive 1"` |
| control: `EACH_QUORUM` writes need every DC | fails with `"Requires 1, alive 0"` |

## Running it

Start a two-node, two-datacenter cluster (one node per DC, `GossipingPropertyFileSnitch`):

```bash
docker network create scylla-cl-net --subnet 172.31.77.0/24

for n in 1 2; do
  docker create --name scylla-dc$n --network scylla-cl-net --ip 172.31.77.1$n \
    scylladb/scylla:6.2 --seeds 172.31.77.11 --smp 1 --memory 1200M \
    --overprovisioned 1 --endpoint-snitch GossipingPropertyFileSnitch
  docker cp dc$n-rackdc.properties scylla-dc$n:/etc/scylla/cassandra-rackdc.properties
  docker start scylla-dc$n
done

# wait until both report UN
docker exec scylla-dc1 nodetool status
```

The rack/DC config is copied in with `docker cp` rather than bind-mounted, because a bind-mounted
`/etc/scylla/cassandra-rackdc.properties` is unreadable by the in-container scylla user on macOS
and the node refuses to start.

Container IPs are not routable from a macOS host, so run the checks from a container on the same
network:

```bash
docker run -d --name cl-tester --network scylla-cl-net python:3.12-slim sleep infinity
docker exec cl-tester pip install --quiet cassandra-driver
docker cp verify_cl_semantics.py cl-tester:/verify.py

docker exec cl-tester python /verify.py phase1   # both DCs up
docker stop scylla-dc1                           # take a whole DC down
docker exec cl-tester python /verify.py phase2   # LOCAL_* scoping
docker start scylla-dc1
```

Teardown:

```bash
docker rm -f scylla-dc1 scylla-dc2 cl-tester
docker network rm scylla-cl-net
```
