from __future__ import annotations

from pathlib import Path
import unittest

from jarvis_core.services.always_on_context import (
    AlwaysOnContextIntegrityError,
    RESERVED_INTERACTION_SLOT_PRIORITY,
    build_memory1_always_on_context,
)


class _Enum:
    def __init__(
        self,
        value,
    ):
        self.value = value


class _Property:
    def __init__(
        self,
        property_id,
        *,
        kind="FACT",
        cardinality="SINGLE_CURRENT",
        value_type="STRING",
        status="ACTIVE",
    ):
        self.id = property_id
        self.kind = _Enum(kind)
        self.cardinality = _Enum(
            cardinality
        )
        self.value_type = _Enum(
            value_type
        )
        self.status = _Enum(
            status
        )


class _Value:
    def __init__(
        self,
        value,
        *,
        value_type="STRING",
    ):
        self.value_type = _Enum(
            value_type
        )
        self.value = value


class _Fact:
    def __init__(
        self,
        property_id,
        value,
        *,
        status="ACTIVE",
        value_type="STRING",
    ):
        self.property_id = property_id
        self.value = _Value(
            value,
            value_type=value_type,
        )
        self.status = _Enum(
            status
        )


class _FakeStore:
    def __init__(
        self,
        bindings=None,
        properties=None,
        facts=None,
    ):
        self.bindings = dict(
            bindings
            or {}
        )

        self.properties = dict(
            properties
            or {}
        )

        self.facts = dict(
            facts
            or {}
        )

    def list_reserved_property_bindings(
        self,
    ):
        return tuple(
            sorted(
                self.bindings.items()
            )
        )

    def list_properties(
        self,
    ):
        return tuple(
            self.properties[
                property_id
            ]
            for property_id
            in sorted(
                self.properties
            )
        )

    def query_current_facts(
        self,
        *,
        subject_entity_ids,
        property_ids=None,
    ):
        self.last_subjects = (
            subject_entity_ids
        )

        allowed = set(
            property_ids
            or ()
        )

        result = []

        for property_id in allowed:
            rows = self.facts.get(
                property_id,
                (),
            )

            if isinstance(
                rows,
                _Fact,
            ):
                rows = (
                    rows,
                )

            result.extend(
                rows
            )

        return tuple(
            result
        )


def _store_for(
    values,
):
    bindings = {}
    properties = {}
    facts = {}

    for index, (
        slot_name,
        value,
    ) in enumerate(
        values.items(),
        start=1,
    ):
        property_id = (
            "property_test_"
            + str(index)
        )

        bindings[
            slot_name
        ] = property_id

        properties[
            property_id
        ] = _Property(
            property_id
        )

        facts[
            property_id
        ] = _Fact(
            property_id,
            value,
        )

    return _FakeStore(
        bindings=bindings,
        properties=properties,
        facts=facts,
    )


class Memory1AlwaysOnContextTests(
    unittest.TestCase
):
    def test_language_is_read_from_reserved_memory1_state(
        self,
    ):
        store = _store_for({
            "interaction.language":
                "pt-PT",
        })

        result = (
            build_memory1_always_on_context(
                store,
                "owner-1",
            )
        )

        self.assertEqual(
            result.bound_slots,
            (
                "interaction.language",
            ),
        )

        self.assertEqual(
            result.included_slots,
            (
                "interaction.language",
            ),
        )

        self.assertEqual(
            result.dropped_slots,
            (),
        )

        self.assertIn(
            'interaction.language="pt-PT"',
            result.context,
        )

        self.assertEqual(
            store.last_subjects,
            (
                "owner-1",
            ),
        )

    def test_next_build_reads_changed_canonical_value_without_cache(
        self,
    ):
        store = _store_for({
            "interaction.language":
                "pt-PT",
        })

        first = (
            build_memory1_always_on_context(
                store,
                "owner-1",
            )
        )

        property_id = (
            store.bindings[
                "interaction.language"
            ]
        )

        store.facts[
            property_id
        ] = _Fact(
            property_id,
            "en-GB",
        )

        second = (
            build_memory1_always_on_context(
                store,
                "owner-1",
            )
        )

        self.assertIn(
            '"pt-PT"',
            first.context,
        )

        self.assertNotIn(
            '"pt-PT"',
            second.context,
        )

        self.assertIn(
            '"en-GB"',
            second.context,
        )

    def test_fixed_priority_discards_lower_priority_slots_at_cap(
        self,
    ):
        language_only = _store_for({
            "interaction.language":
                "pt-PT",
        })

        language_result = (
            build_memory1_always_on_context(
                language_only,
                "owner-1",
            )
        )

        full = _store_for({
            "interaction.language":
                "pt-PT",
            "interaction.address_form":
                "Tiago",
            "interaction.verbosity":
                "concise",
        })

        capped = (
            build_memory1_always_on_context(
                full,
                "owner-1",
                max_chars=len(
                    language_result.context
                ),
            )
        )

        self.assertEqual(
            RESERVED_INTERACTION_SLOT_PRIORITY,
            (
                "interaction.language",
                "interaction.address_form",
                "interaction.verbosity",
            ),
        )

        self.assertEqual(
            capped.included_slots,
            (
                "interaction.language",
            ),
        )

        self.assertEqual(
            capped.dropped_slots,
            (
                "interaction.address_form",
                "interaction.verbosity",
            ),
        )

        self.assertLessEqual(
            capped.char_count,
            capped.max_chars,
        )

    def test_unbound_slots_do_not_create_global_behavior(
        self,
    ):
        result = (
            build_memory1_always_on_context(
                _FakeStore(),
                "owner-1",
            )
        )

        self.assertEqual(
            result.context,
            "",
        )

        self.assertEqual(
            result.included_slots,
            (),
        )

    def test_multiple_current_facts_fail_closed(
        self,
    ):
        store = _store_for({
            "interaction.language":
                "pt-PT",
        })

        property_id = (
            store.bindings[
                "interaction.language"
            ]
        )

        store.facts[
            property_id
        ] = (
            _Fact(
                property_id,
                "pt-PT",
            ),
            _Fact(
                property_id,
                "en-GB",
            ),
        )

        with self.assertRaises(
            AlwaysOnContextIntegrityError
        ):
            build_memory1_always_on_context(
                store,
                "owner-1",
            )

    def test_wrong_reserved_property_contract_fails_closed(
        self,
    ):
        store = _store_for({
            "interaction.language":
                "pt-PT",
        })

        property_id = (
            store.bindings[
                "interaction.language"
            ]
        )

        store.properties[
            property_id
        ] = _Property(
            property_id,
            cardinality="MULTI_CURRENT",
        )

        with self.assertRaises(
            AlwaysOnContextIntegrityError
        ):
            build_memory1_always_on_context(
                store,
                "owner-1",
            )

    def test_builder_has_no_personal_cognition_authority_path(
        self,
    ):
        root = Path(
            __file__
        ).resolve().parents[1]

        source = (
            root
            / "jarvis_core"
            / "services"
            / "always_on_context.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "personal_cognition",
            source,
        )

        self.assertNotIn(
            "personal_model",
            source,
        )

    def test_brain_startup_no_longer_injects_ambient_personal_model(
        self,
    ):
        root = Path(
            __file__
        ).resolve().parents[1]

        source = (
            root
            / "jarvis_core"
            / "core"
            / "brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "Local personal model "
            "(OWNER facts only",
            source,
        )

        self.assertNotIn(
            "Address the user as:",
            source,
        )

    def test_explicit_always_on_transport_seam_exists_end_to_end(
        self,
    ):
        root = Path(
            __file__
        ).resolve().parents[1]

        runtime = (
            root
            / "jarvis_core"
            / "runtime.py"
        ).read_text(
            encoding="utf-8"
        )

        hybrid = (
            root
            / "jarvis_core"
            / "core"
            / "hybrid_brain.py"
        ).read_text(
            encoding="utf-8"
        )

        brain = (
            root
            / "jarvis_core"
            / "core"
            / "brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "build_memory1_always_on_context",
            runtime,
        )

        self.assertIn(
            "always_on_context",
            runtime,
        )

        self.assertIn(
            "always_on_context",
            hybrid,
        )

        self.assertIn(
            "always_on_context",
            brain,
        )

        self.assertIn(
            "JARVIS_ALWAYS_ON_INTERACTION:",
            brain,
        )


if __name__ == "__main__":
    unittest.main()
