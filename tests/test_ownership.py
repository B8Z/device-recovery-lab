"""Independent acceptance for shared durable work, including stale-worker rejection."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from lab.common import database
from lab.service import LostLease, Service


class OwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "service.db"
        self.service = Service(self.path, "http://127.0.0.1:1")
        self.run_id = str(uuid.uuid4())
        self.service.create({"id": self.run_id, "scenario": "healthy"})

    def tearDown(self):
        self.temp.cleanup()

    def test_racing_claims_have_one_owner(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            claims = list(pool.map(lambda _: self.service.claim(self.run_id, 0), range(24)))
        self.assertEqual(1, sum(c is not None for c in claims))

    def test_expired_owner_cannot_write_events_regress_state_or_release_successor(self):
        old = self.service.claim(self.run_id, 0)
        self.service.record_owned(old, "COMMAND_SENT", "Intent precedes I/O", state="UNCERTAIN", sends=1)
        with database(self.path) as con:
            con.execute("UPDATE runs SET lease_until=? WHERE id=?", (time.time()-1, self.run_id))
        # Reopen the journal as a replacement service would after interruption.
        replacement = Service(self.path, "http://127.0.0.1:1")
        new = replacement.claim(self.run_id, old["epoch"])
        self.assertEqual("UNCERTAIN", new["state"])
        self.assertEqual(old["epoch"]+1, new["epoch"])
        replacement.record_owned(new, "COMPLETION_CONFIRMED", "New owner observed completion", state="COMPLETED")
        with self.assertRaises(LostLease):
            self.service.record_owned(old, "STALE_WRITE", "Late response", state="ACCEPTED")
        self.service.release(old)
        with database(self.path) as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (self.run_id,)).fetchone()
            self.assertEqual("COMPLETED", row["state"])
            self.assertEqual(new["lease_owner"], row["lease_owner"])
            self.assertEqual(0, con.execute("SELECT count(*) FROM events WHERE kind='STALE_WRITE'").fetchone()[0])

    def test_stale_candidate_cannot_reclaim_even_after_owner_releases(self):
        old = self.service.claim(self.run_id, 0)
        self.service.release(old)
        self.assertIsNone(self.service.claim(self.run_id, 0))
        self.assertIsNotNone(self.service.claim(self.run_id, old["epoch"]))

    def test_existing_journal_migration_is_idempotent_and_preserves_operations(self):
        # Construct the earlier schema independently instead of asking the new
        # initializer to create the database it will then "migrate".
        legacy = Path(self.temp.name) / "legacy.db"
        with database(legacy) as con:
            con.execute("""CREATE TABLE runs(id TEXT PRIMARY KEY,scenario TEXT NOT NULL,
                state TEXT NOT NULL,created REAL NOT NULL,next_at REAL NOT NULL,
                sends INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,
                checks INTEGER NOT NULL DEFAULT 0,duplicate_sent INTEGER NOT NULL DEFAULT 0,
                reconciled INTEGER NOT NULL DEFAULT 0)""")
            con.execute("INSERT INTO runs(id,scenario,state,created,next_at,sends) VALUES(?,'healthy','UNCERTAIN',0,0,1)", (self.run_id,))
        for _ in range(2):
            migrated = Service(legacy, "http://127.0.0.1:1")
        claim = migrated.claim(self.run_id, 0)
        self.assertEqual(("UNCERTAIN", 1, 1), (claim["state"], claim["sends"], claim["epoch"]))
