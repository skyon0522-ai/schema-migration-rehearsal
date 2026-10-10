# Source concepts behind the fixed rehearsal

This example uses an inspected original implementation as its reference: Alembic commit `1bc21b86dd6ddd07ac696e2d73b6cb200dd97bbd`. The upstream [PostgreSQL enum test](components/alembic/tests/test_postgresql.py) provides the three-label fixture and `ADD VALUE 'soso'` operation. The copied [autocommit implementation](components/alembic/alembic/runtime/migration.py) supplies the transaction boundary actually executed. The source/behavior mapping is recorded in [PROVENANCE.md](PROVENANCE.md).

The implementation's `autocommit_block` docstring warns that it commits the preceding database transaction. It temporarily uses DBAPI autocommit for the operation and restores the prior isolation level afterward. That behavior motivates the separate marker transaction here: after the durable enum change but before marker commit, a fresh connection can observe a state that an exception-only rollback test would miss. The example observes that state by killing a real worker and reconnecting.

Conditional completion is valid only when the inspected schema, label order, original rows, stored-value set and marker agree with the fixed contract. `IF NOT EXISTS` handles the expected already-added label after this validation. It provides no evidence that an arbitrary changed database is safe to resume. The seven drift cases test this distinction directly.

Adding a label to an enum catalog also does not make an older closed-set parser accept that label in stored rows. The compatibility gate keeps old-label writes working and prevents premature storage of `soso`. A separate activation control stores `soso` and makes the unchanged reader fail, demonstrating the boundary of the claim.

These are observations about this one implementation and synthetic client. PostgreSQL 18 does not always require nontransactional `ADD VALUE`; the evidence establishes the chosen copied autocommit execution, rather than a universal PostgreSQL requirement. No general theorem about crash recovery, migration orchestration, concurrent deployment or production availability follows from these scenarios.

The reproduction evidence also separates acquiring dependencies from running the client contract. Fresh acquisition verified the 26 pinned official artifacts; the installed set additionally contained bootstrap pip 24.0, giving 27 observed distributions. The separate psycopg2 build and actual offline-from-fresh-wheelhouse installation were recorded before the same unchanged adapter passed. Artifact hashes establish the retained bytes for this profile. They do not establish bit-reproducible compilation, general cross-machine execution or a fresh PostgreSQL installation. The easier version-only try command does not inherit every control of that observed pipeline.

## Research background

Ian Rae, Eric Rollins, Jeff Shute, Sukhdeep Sodhi and Radek Vingralek,
*[Online, Asynchronous Schema Change in F1](https://www.vldb.org/pvldb/vol6/p1045-rae.pdf)*,
Proceedings of the VLDB Endowment 6(11), 1045–1056 (2013).

Section 3 develops intermediate schema states that preserve consistency while
different schema users coexist. Section 4.4 requires resumable, idempotent data
reorganization when atomic completion is impractical. We adapt these ideas as
test-design questions: do the fixed old-client operations remain valid while
the gate is present, and does completion resume after durable expansion without
changing an already-completed state? The gate, interruption and second-resume
fixtures answer those questions only for this synthetic contract.

This is a research analogy, not an implementation of F1's protocol. The example
does not reproduce schema leases, write fencing, a distributed reorganizer, the
formal proof or production measurements, and inherits no distributed correctness
or zero-downtime guarantee from the paper.

