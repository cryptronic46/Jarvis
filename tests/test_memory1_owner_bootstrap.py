from __future__ import annotations

import ast
import inspect
import tempfile
from pathlib import Path
import unittest

import jarvis_core.memory.owner_bootstrap as owner_module

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)

from jarvis_core.memory.enums import (
    MemoryNamespace,
)

from jarvis_core.memory.errors import (
    MemoryIntegrityError,
)

from jarvis_core.memory.models import (
    Entity,
)

from jarvis_core.memory.owner_bootstrap import (
    ensure_canonical_owner,
)


class OwnerBootstrapTests(
    unittest.TestCase
):
    def setUp(
        self,
    ) -> None:
        self.tmp = (
            tempfile.TemporaryDirectory()
        )

        self.path = (
            Path(
                self.tmp.name
            )
            / "memory.sqlite3"
        )

        self.store = (
            CanonicalMemoryStore(
                self.path
            )
        )

    def tearDown(
        self,
    ) -> None:
        self.tmp.cleanup()

    def owners(
        self,
    ):
        return tuple(
            entity
            for entity
            in self.store
            .list_entities()
            if (
                entity.namespace
                is MemoryNamespace.OWNER
            )
        )

    def module_source(
        self,
    ) -> str:
        return Path(
            owner_module.__file__
        ).read_text(
            encoding="utf-8"
        )

    def module_tree(
        self,
    ) -> ast.Module:
        return ast.parse(
            self.module_source()
        )

    # 01
    def test_fresh_store_creates_owner(
        self,
    ) -> None:
        self.assertEqual(
            self.owners(),
            (),
        )

        ensure_canonical_owner(
            self.store
        )

        owners = self.owners()

        self.assertEqual(
            len(
                owners
            ),
            1,
        )

        owner = owners[
            0
        ]

        self.assertEqual(
            owner.canonical_name,
            "owner",
        )

        self.assertEqual(
            owner.entity_type,
            "person",
        )

        self.assertIs(
            owner.namespace,
            MemoryNamespace.OWNER,
        )

    # 02
    def test_fresh_store_returns_trusted_binding(
        self,
    ) -> None:
        bindings = (
            ensure_canonical_owner(
                self.store
            )
        )

        owner = self.owners()[
            0
        ]

        self.assertEqual(
            bindings
            .canonical_id_for(
                "owner"
            ),
            owner.id,
        )

        self.assertEqual(
            bindings.local_refs(),
            (
                "owner",
            ),
        )

    # 03
    def test_create_consumes_exactly_one_revision(
        self,
    ) -> None:
        before = (
            self.store
            .canonical_revision()
        )

        ensure_canonical_owner(
            self.store
        )

        after = (
            self.store
            .canonical_revision()
        )

        self.assertEqual(
            before,
            0,
        )

        self.assertEqual(
            after,
            1,
        )

        self.assertEqual(
            after,
            before + 1,
        )

        ok, problems = (
            self.store
            .verify_audit_chain()
        )

        self.assertTrue(
            ok,
            problems,
        )

    # 04
    def test_second_call_reuses_same_owner_id(
        self,
    ) -> None:
        first = (
            ensure_canonical_owner(
                self.store
            )
        )

        first_id = (
            first
            .canonical_id_for(
                "owner"
            )
        )

        second = (
            ensure_canonical_owner(
                self.store
            )
        )

        second_id = (
            second
            .canonical_id_for(
                "owner"
            )
        )

        self.assertEqual(
            second_id,
            first_id,
        )

        self.assertEqual(
            len(
                self.owners()
            ),
            1,
        )

    # 05
    def test_second_call_consumes_no_revision(
        self,
    ) -> None:
        ensure_canonical_owner(
            self.store
        )

        before = (
            self.store
            .canonical_revision()
        )

        ensure_canonical_owner(
            self.store
        )

        after = (
            self.store
            .canonical_revision()
        )

        self.assertEqual(
            before,
            1,
        )

        self.assertEqual(
            after,
            before,
        )

    # 06
    def test_owner_has_no_synthetic_source_episode(
        self,
    ) -> None:
        ensure_canonical_owner(
            self.store
        )

        owner = self.owners()[
            0
        ]

        self.assertEqual(
            owner.source_episode_ids,
            (),
        )

        self.assertEqual(
            owner.confidence,
            1.0,
        )

    # 07
    def test_multiple_owner_fails_closed(
        self,
    ) -> None:
        tx = (
            self.store
            .begin_transaction(
                actor_entity_id=None
            )
        )

        tx.create_entity(
            Entity.create(
                namespace=(
                    MemoryNamespace.OWNER
                ),
                canonical_name="owner",
                entity_type="person",
            )
        )

        tx.create_entity(
            Entity.create(
                namespace=(
                    MemoryNamespace.OWNER
                ),
                canonical_name="owner",
                entity_type="person",
            )
        )

        tx.commit()

        before = (
            self.store
            .canonical_revision()
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            ensure_canonical_owner(
                self.store
            )

        after = (
            self.store
            .canonical_revision()
        )

        self.assertEqual(
            len(
                self.owners()
            ),
            2,
        )

        self.assertEqual(
            after,
            before,
        )

    # 08
    def test_invalid_owner_fails_closed(
        self,
    ) -> None:
        tx = (
            self.store
            .begin_transaction(
                actor_entity_id=None
            )
        )

        tx.create_entity(
            Entity.create(
                namespace=(
                    MemoryNamespace.OWNER
                ),
                canonical_name="owner",
                entity_type="device",
            )
        )

        tx.commit()

        before = (
            self.store
            .canonical_revision()
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            ensure_canonical_owner(
                self.store
            )

        after = (
            self.store
            .canonical_revision()
        )

        self.assertEqual(
            after,
            before,
        )

        self.assertEqual(
            len(
                self.owners()
            ),
            1,
        )

    # 09
    def test_transaction_first_lock_guard(
        self,
    ) -> None:
        source = inspect.getsource(
            ensure_canonical_owner
        )

        tree = ast.parse(
            source
        )

        begin_lines = []

        list_lines = []

        for node in ast.walk(
            tree
        ):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            if isinstance(
                node.func,
                ast.Attribute,
            ):
                if (
                    node.func.attr
                    == "begin_transaction"
                ):
                    begin_lines.append(
                        node.lineno
                    )

                if (
                    node.func.attr
                    == "list_entities"
                ):
                    list_lines.append(
                        node.lineno
                    )

        self.assertTrue(
            begin_lines
        )

        self.assertTrue(
            list_lines
        )

        self.assertLess(
            min(
                begin_lines
            ),
            min(
                list_lines
            ),
        )

        store_source = inspect.getsource(
            CanonicalMemoryStore
            .begin_transaction
        )

        transaction = (
            self.store
            .begin_transaction(
                actor_entity_id=None
            )
        )

        tx_type = type(
            transaction
        )

        constructor_source = (
            inspect.getsource(
                tx_type.__init__
            )
        )

        transaction.rollback()

        lock_source = (
            store_source
            + "\n"
            + constructor_source
        )

        self.assertIn(
            "BEGIN IMMEDIATE",
            lock_source,
        )

    # 10
    def test_no_semantic_or_model_dependencies(
        self,
    ) -> None:
        source = (
            self.module_source()
        )

        tree = self.module_tree()

        imported = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imported.extend(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                imported.append(
                    node.module
                    or ""
                )

        forbidden_import_tokens = (
            "qwen",
            "resolution",
            "interpreter",
            "sqlite3",
            "regex",
        )

        self.assertFalse(
            any(
                token
                in module.casefold()
                for module
                in imported
                for token
                in forbidden_import_tokens
            )
        )

        self.assertNotIn(
            "new_memory_id",
            source,
        )

        self.assertNotIn(
            "canonical_id=",
            source,
        )

        self.assertNotIn(
            "raw_text",
            source,
        )

        self.assertNotIn(
            "synonym",
            source.casefold(),
        )

        self.assertNotIn(
            "import re",
            source,
        )

        self.assertNotIn(
            "execute(",
            source,
        )


if __name__ == "__main__":
    unittest.main()
