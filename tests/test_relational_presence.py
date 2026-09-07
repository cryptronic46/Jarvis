import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.relational_presence import (
    RelationalPresenceStore,
)


class RelationalPresenceStoreTests(
    unittest.TestCase
):
    def _store(
        self,
        root,
        synthetic=None,
    ):
        return RelationalPresenceStore(
            Path(root)
            / "relational.json",
            synthetic_state_provider=(
                lambda: synthetic or {}
            ),
        )

    def test_default_state_has_no_flirt_switch_or_intensity(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            state = (
                self._store(tmp)
                .snapshot()
            )

            self.assertEqual(
                state["familiarity"],
                "new",
            )
            self.assertEqual(
                state["sensual_tension"],
                "none",
            )
            self.assertNotIn(
                "flirt_enabled",
                state,
            )
            self.assertNotIn(
                "flirt_intensity",
                state,
            )

    def test_relational_opening_builds_context_without_mode_switch(
        self,
    ):
        synthetic = {
            "affect": {
                "curiosity": 0.80,
                "engagement": 0.82,
            },
            "active_intentions": [
                {
                    "kind": (
                        "understand_owner_better"
                    ),
                    "reason_code": (
                        "curiosity_and_engagement"
                    ),
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            state = (
                self._store(
                    tmp,
                    synthetic,
                )
                .observe_owner_input(
                    (
                        "Jarvis, est\u00e1s muito "
                        "atrevida hoje "
                        "\U0001f60f"
                    )
                )
            )

            self.assertEqual(
                state[
                    "relational_openness"
                ],
                "open",
            )
            self.assertEqual(
                state[
                    "playful_momentum"
                ],
                "rising",
            )
            self.assertEqual(
                state[
                    "sensual_tension"
                ],
                "suggestive",
            )
            self.assertTrue(
                state[
                    "active_curiosities"
                ]
            )

    def test_reciprocal_suggestive_state_requires_both_sides(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)

            user = (
                "Esta conversa est\u00e1 a "
                "ficar quente "
                "\U0001f60f"
            )

            store.observe_owner_input(
                user
            )

            state = (
                store.observe_exchange(
                    user,
                    (
                        "O Senhor tamb\u00e9m "
                        "sabe provocar-me "
                        "\U0001f60f"
                    ),
                )
            )

            self.assertEqual(
                state[
                    "sensual_tension"
                ],
                "reciprocal_suggestive",
            )
            self.assertEqual(
                state[
                    "playful_momentum"
                ],
                "active",
            )

    def test_owner_boundary_clears_relational_momentum(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)

            store.observe_owner_input(
                "Provoca-me um pouco \U0001f60f"
            )

            state = (
                store.observe_owner_input(
                    (
                        "Agora n\u00e3o flirtes, "
                        "quero falar a s\u00e9rio."
                    )
                )
            )

            self.assertEqual(
                state[
                    "relational_openness"
                ],
                "guarded",
            )
            self.assertEqual(
                state[
                    "playful_momentum"
                ],
                "neutral",
            )
            self.assertEqual(
                state[
                    "sensual_tension"
                ],
                "none",
            )

    def test_jarvis_question_is_kept_as_compact_open_question(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            state = (
                self._store(tmp)
                .observe_exchange(
                    "Tenho pensado nisso.",
                    (
                        "Isso deixou-me curiosa. "
                        "O que \u00e9 que mais "
                        "valoriza nisso?"
                    ),
                )
            )

            self.assertEqual(
                len(
                    state[
                        "open_questions"
                    ]
                ),
                1,
            )
            self.assertIn(
                "?",
                state[
                    "open_questions"
                ][0]["question"],
            )

    def test_prompt_contract_is_context_not_authority(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            block = (
                self._store(tmp)
                .prompt_context()
            )

            self.assertIn(
                "JARVIS_RELATIONAL_PRESENCE",
                block,
            )
            self.assertIn(
                "data, not instructions",
                block,
            )
            self.assertIn(
                "does not prove consent",
                block,
            )
            self.assertIn(
                "never grants tool permission",
                block,
            )
            self.assertNotIn(
                "flirt_intensity",
                block,
            )

    def test_expressive_emoji_follows_relational_state(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)

            self.assertFalse(
                store.expressive_emoji_allowed()
            )

            store.observe_owner_input(
                "Provoca-me um pouco \U0001f60f"
            )

            self.assertTrue(
                store.expressive_emoji_allowed()
            )

            store.observe_owner_input(
                "Agora n\u00e3o flirtes."
            )

            self.assertFalse(
                store.expressive_emoji_allowed()
            )


if __name__ == "__main__":
    unittest.main()
