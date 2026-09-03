import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.autonomy import (
    AuthorizedLearningStore,
)


class AuthorizedLearningTests(unittest.TestCase):
    def test_store_and_search(self):
        with tempfile.TemporaryDirectory() as td:
            store = AuthorizedLearningStore(
                Path(td) / "learning.jsonl"
            )
            result = store.add(
                topic="Python",
                query="novidades Python",
                summary="Python tem novidades relevantes.",
                model="test-model",
                authorization_token="ABC123",
            )
            self.assertTrue(
                result["stored"]
            )

            found = store.search(
                "Python"
            )
            self.assertEqual(
                found["count"],
                1,
            )
            self.assertEqual(
                found["results"][0][
                    "authority"
                ],
                "explicit_owner_authorization",
            )
            self.assertEqual(
                found["results"][0][
                    "source_type"
                ],
                "authorized_web_research_model_summary",
            )


if __name__ == "__main__":
    unittest.main()
