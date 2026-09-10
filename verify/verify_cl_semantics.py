"""Verify the consistency-level semantics the HA simulator claims to teach, against a real
two-datacenter ScyllaDB cluster (DC1: 172.31.77.11, DC2: 172.31.77.12).

Runs inside a container on the cluster's docker network, in two phases so the host can stop a
whole datacenter in between:

  phase1 (both DCs up)
    #7  NetworkTopologyStrategy takes an independent RF per datacenter.
    #6  ANY reads are rejected by the server (writes are fine).
    #3  EACH_QUORUM reads are rejected by the server (writes are fine).

  phase2 (DC1 stopped, coordinator pinned to DC2)
    #4  LOCAL_* is scoped to the COORDINATOR's datacenter, not the client's configured local DC.
        Controls: cluster-wide QUORUM and EACH_QUORUM writes must both fail with a DC down.
"""

import sys

from cassandra import ConsistencyLevel, InvalidRequest, Unavailable
from cassandra.cluster import Cluster, ExecutionProfile, EXEC_PROFILE_DEFAULT, NoHostAvailable
from cassandra.policies import WhiteListRoundRobinPolicy
from cassandra.query import SimpleStatement

DC1_IP = "172.31.77.11"
DC2_IP = "172.31.77.12"

results = []


def record(check, expectation, outcome, passed):
    results.append((check, passed))
    print(f"[{'PASS' if passed else 'FAIL'}] {check}\n       expected: {expectation}\n       actual:   {outcome}\n")


def session_pinned_to(ip):
    """A session that can only ever use `ip` as coordinator. Pinning the host lets us drive a
    coordinator in one DC while the driver's own notion of a local DC points elsewhere."""
    profile = ExecutionProfile(
        load_balancing_policy=WhiteListRoundRobinPolicy([ip]), request_timeout=30
    )
    cluster = Cluster([ip], protocol_version=4, execution_profiles={EXEC_PROFILE_DEFAULT: profile})
    return cluster, cluster.connect()


def phase1():
    cluster, session = session_pinned_to(DC1_IP)

    print("=== cluster topology ===")
    local = session.execute("SELECT listen_address, data_center, rack FROM system.local").one()
    print(f"  local {local.listen_address} dc={local.data_center} rack={local.rack}")
    for row in session.execute("SELECT peer, data_center, rack FROM system.peers"):
        print(f"  peer  {row.peer} dc={row.data_center} rack={row.rack}")
    print()

    # --- #7: NetworkTopologyStrategy with an independent RF per DC -----------------------------
    session.execute("DROP KEYSPACE IF EXISTS cl_probe")
    session.execute(
        "CREATE KEYSPACE cl_probe WITH replication = "
        "{'class': 'NetworkTopologyStrategy', 'DC1': 1, 'DC2': 1}"
    )
    session.execute("CREATE TABLE cl_probe.t (k text PRIMARY KEY, v int)")
    replication = session.execute(
        "SELECT replication FROM system_schema.keyspaces WHERE keyspace_name = 'cl_probe'"
    ).one().replication
    record(
        "#7 per-DC replication factor",
        "NetworkTopologyStrategy accepts a separate RF per DC",
        f"stored replication = {dict(replication)}",
        replication.get("DC1") == "1" and replication.get("DC2") == "1",
    )

    # --- #6: ANY is write-only ----------------------------------------------------------------
    session.execute(SimpleStatement(
        "INSERT INTO cl_probe.t (k, v) VALUES ('any', 1)",
        consistency_level=ConsistencyLevel.ANY,
    ))
    print("       (ANY write succeeded, as expected)")
    try:
        session.execute(SimpleStatement(
            "SELECT * FROM cl_probe.t WHERE k = 'any'", consistency_level=ConsistencyLevel.ANY
        ))
        record("#6 ANY read", "server rejects the read", "read was ACCEPTED", False)
    except InvalidRequest as exc:
        record("#6 ANY read", "server rejects the read", f"InvalidRequest: {exc}", True)

    # --- #3: EACH_QUORUM is write-only --------------------------------------------------------
    session.execute(SimpleStatement(
        "INSERT INTO cl_probe.t (k, v) VALUES ('eq', 1)",
        consistency_level=ConsistencyLevel.EACH_QUORUM,
    ))
    print("       (EACH_QUORUM write succeeded, as expected)")
    try:
        session.execute(SimpleStatement(
            "SELECT * FROM cl_probe.t WHERE k = 'eq'",
            consistency_level=ConsistencyLevel.EACH_QUORUM,
        ))
        record("#3 EACH_QUORUM read", "server rejects the read", "read was ACCEPTED", False)
    except InvalidRequest as exc:
        record("#3 EACH_QUORUM read", "server rejects the read", f"InvalidRequest: {exc}", True)

    # Seed a row into both DCs so phase 2 has data to find.
    session.execute(SimpleStatement(
        "INSERT INTO cl_probe.t (k, v) VALUES ('local', 42)",
        consistency_level=ConsistencyLevel.ALL,
    ))
    print("       (seeded k='local' at CL=ALL so both DCs hold it)\n")
    cluster.shutdown()


def phase2():
    # DC1 is stopped by the caller. Pin the coordinator to DC2's node. If "local" followed the
    # CLIENT's local DC (DC1), LOCAL_QUORUM would need DC1's dead replica; if it follows the
    # COORDINATOR's DC (DC2), it only needs DC2's own live replica.
    cluster, session = session_pinned_to(DC2_IP)
    coord_dc = session.execute("SELECT data_center FROM system.local").one().data_center
    print(f"=== coordinator pinned to {DC2_IP} (dc={coord_dc}); DC1 is down ===\n")

    try:
        rows = session.execute(SimpleStatement(
            "SELECT v FROM cl_probe.t WHERE k = 'local'",
            consistency_level=ConsistencyLevel.LOCAL_QUORUM,
        ))
        record(
            "#4 LOCAL_QUORUM with DC1 down, coordinator in DC2",
            "succeeds -> 'local' means the COORDINATOR's DC",
            f"read succeeded, v={[r.v for r in rows]}",
            True,
        )
    except (Unavailable, NoHostAvailable) as exc:
        record(
            "#4 LOCAL_QUORUM with DC1 down, coordinator in DC2",
            "succeeds -> 'local' means the COORDINATOR's DC",
            f"{type(exc).__name__}: {exc}",
            False,
        )

    # Control: a cluster-wide QUORUM over RF DC1:1 + DC2:1 needs 2 of 2 replicas, so it MUST
    # fail with DC1 down. This proves the LOCAL_QUORUM success above was actually meaningful.
    try:
        session.execute(SimpleStatement(
            "SELECT v FROM cl_probe.t WHERE k = 'local'",
            consistency_level=ConsistencyLevel.QUORUM,
        ))
        record(
            "control: cluster-wide QUORUM with DC1 down",
            "fails (needs 2/2 replicas across both DCs)",
            "read was ACCEPTED",
            False,
        )
    except (Unavailable, NoHostAvailable) as exc:
        record(
            "control: cluster-wide QUORUM with DC1 down",
            "fails (needs 2/2 replicas across both DCs)",
            f"{type(exc).__name__}: {exc}",
            True,
        )

    # EACH_QUORUM writes must fail too: DC1 can't reach its own quorum while it's down.
    try:
        session.execute(SimpleStatement(
            "INSERT INTO cl_probe.t (k, v) VALUES ('eq2', 2)",
            consistency_level=ConsistencyLevel.EACH_QUORUM,
        ))
        record(
            "EACH_QUORUM write with DC1 down",
            "fails (DC1 cannot reach its own quorum)",
            "write was ACCEPTED",
            False,
        )
    except (Unavailable, NoHostAvailable) as exc:
        record(
            "EACH_QUORUM write with DC1 down",
            "fails (DC1 cannot reach its own quorum)",
            f"{type(exc).__name__}: {exc}",
            True,
        )

    # LOCAL_ONE should behave the same way as LOCAL_QUORUM here (RF 1 in DC2 -> quorum is 1).
    try:
        rows = session.execute(SimpleStatement(
            "SELECT v FROM cl_probe.t WHERE k = 'local'",
            consistency_level=ConsistencyLevel.LOCAL_ONE,
        ))
        record(
            "#4 LOCAL_ONE with DC1 down, coordinator in DC2",
            "succeeds against the coordinator's own DC",
            f"read succeeded, v={[r.v for r in rows]}",
            True,
        )
    except (Unavailable, NoHostAvailable) as exc:
        record(
            "#4 LOCAL_ONE with DC1 down, coordinator in DC2",
            "succeeds against the coordinator's own DC",
            f"{type(exc).__name__}: {exc}",
            False,
        )

    cluster.shutdown()


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "phase1"
    {"phase1": phase1, "phase2": phase2}[phase]()

    print("=" * 70)
    passed = sum(1 for _, ok in results if ok)
    print(f"{phase} SUMMARY: {passed}/{len(results)} checks passed")
    for check, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {check}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
