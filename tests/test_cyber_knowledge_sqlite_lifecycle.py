import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.cyber_knowledge import CyberKnowledgeVault


class CyberKnowledgeSQLiteLifecycleTests(unittest.TestCase):
    def make(self):
        root = Path(tempfile.mkdtemp())
        sources = root / "sources.json"
        sources.write_text('{"sources":[]}', encoding="utf-8")
        vault = CyberKnowledgeVault(
            db_path=root / "knowledge.sqlite3",
            sources_path=sources,
            state_path=root / "state.json",
        )
        return root, vault

    def test_db_can_be_renamed_after_operations(self):
        root, vault = self.make()
        try:
            db = root / "knowledge.sqlite3"
            vault.stats()
            vault.search("RDP")
            vault._upsert(
                source_id="test", external_id="1", title="Test",
                body="Firewall test", publisher="Test", trust="curated",
                provenance="curated-seed",
            )
            gc.collect()
            renamed = root / "renamed.sqlite3"
            db.rename(renamed)
            renamed.rename(db)
        finally:
            shutil.rmtree(root)

    def test_db_closes_after_exception(self):
        root, vault = self.make()
        try:
            db = root / "knowledge.sqlite3"
            with self.assertRaises(RuntimeError):
                with vault._db() as conn:
                    conn.execute("SELECT 1")
                    raise RuntimeError("forced")
            gc.collect()
            renamed = root / "exception.sqlite3"
            db.rename(renamed)
            renamed.rename(db)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
