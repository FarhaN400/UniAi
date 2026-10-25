"""Deterministic regression tests for conversation state isolation and concurrency.

All tests run network-free using mocks (no real MongoDB, Pinecone, or LLM calls).
"""
import concurrent.futures
import unittest
from unittest.mock import MagicMock, patch

from Module4.conversation_state import ConversationState
from Module4.main import ask_uniai, state as global_module_state


class TestConversationStateIsolation(unittest.TestCase):

    def setUp(self):
        # Guarantee no test query hits network or real MongoDB / Pinecone
        self.mock_notice_default = {
            "notice_id": "mock_default_id",
            "title": "Default Mock Notice",
            "url": "https://makautwb.ac.in/default.pdf",
            "structured_data": {
                "title": "Default Mock Notice",
                "issue_date": "01-01-2026",
            },
        }
        self._retrieval_patches = [
            patch("retrieve.retrieve_filtered_notices", return_value=[self.mock_notice_default]),
            patch("retrieve.retrieve_context", return_value=[self.mock_notice_default]),
            patch("retrieve.retrieve_time_based", return_value=[self.mock_notice_default]),
            patch("Module4.main.retrieve_context", create=True, return_value=[self.mock_notice_default]),
        ]
        for p in self._retrieval_patches:
            p.start()

    def tearDown(self):
        for p in self._retrieval_patches:
            p.stop()

    def test_default_state_isolation_without_explicit_state(self):
        """Calls omitting state must use ephemeral ConversationState instances and not share data."""
        initial_global_turns = len(global_module_state.chat_history)

        # Turn 1: Introduce user without passing state
        reply1 = ask_uniai("Hello UniAI, my name is Alice.")
        self.assertIn("Alice", reply1)

        # Global module state must NOT have been mutated
        self.assertEqual(len(global_module_state.chat_history), initial_global_turns)
        self.assertNotEqual(global_module_state.get_user_name(), "Alice")

        # Turn 2: Follow-up without passing state must NOT remember Alice
        reply2 = ask_uniai("Who am I?")
        self.assertNotIn("Alice", reply2)
        self.assertIn("I don't know your name yet", reply2)

    def test_explicit_state_preservation(self):
        """Passing an explicit ConversationState persists turns across calls for that state."""
        custom_state = ConversationState()

        reply1 = ask_uniai("Hello UniAI, my name is Bob.", state=custom_state)
        self.assertIn("Bob", reply1)
        self.assertEqual(custom_state.get_user_name(), "Bob")
        self.assertEqual(len(custom_state.chat_history), 1)

        reply2 = ask_uniai("Who am I?", state=custom_state)
        self.assertIn("Bob", reply2)
        self.assertEqual(len(custom_state.chat_history), 2)

    def test_concurrent_independent_conversations(self):
        """Concurrent conversations using distinct ConversationState instances must not interfere."""
        state_alice = ConversationState()
        state_bob = ConversationState()

        def conversation_flow(name, state):
            # Turn 1: Introduction
            r1 = ask_uniai(f"Hello, my name is {name}.", state=state)
            # Turn 2: Identity check
            r2 = ask_uniai("What is my name?", state=state)
            # Turn 3: Assistant persona check
            r3 = ask_uniai("Who are you?", state=state)
            return r1, r2, r3

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_alice = executor.submit(conversation_flow, "Alice", state_alice)
            future_bob = executor.submit(conversation_flow, "Bob", state_bob)

            # Use future.result() to propagate any concurrency test exceptions
            res_alice = future_alice.result()
            res_bob = future_bob.result()

        # Verify Alice's conversation integrity
        self.assertIn("Alice", res_alice[0])
        self.assertIn("Alice", res_alice[1])
        self.assertNotIn("Bob", res_alice[1])
        self.assertEqual(state_alice.get_user_name(), "Alice")
        self.assertEqual(len(state_alice.chat_history), 3)

        # Verify Bob's conversation integrity
        self.assertIn("Bob", res_bob[0])
        self.assertIn("Bob", res_bob[1])
        self.assertNotIn("Alice", res_bob[1])
        self.assertEqual(state_bob.get_user_name(), "Bob")
        self.assertEqual(len(state_bob.chat_history), 3)

    @patch("Module4.main._safe_grounded_answer")
    def test_concurrent_notice_retrieval_isolation(self, mock_grounded_answer):
        """Verify that concurrent notice searches store active notices in their respective states only."""
        notice_wbjee = {
            "notice_id": "notice_wbjee_101",
            "title": "WBJEE 2026 Reporting Instructions",
            "url": "https://makautwb.ac.in/wbjee.pdf",
            "structured_data": {
                "title": "WBJEE 2026 Reporting Instructions",
                "issue_date": "10-05-2026",
            },
        }
        notice_hostel = {
            "notice_id": "notice_hostel_202",
            "title": "Hostel Closure Order 2026",
            "url": "https://makautwb.ac.in/hostel.pdf",
            "structured_data": {
                "title": "Hostel Closure Order 2026",
                "issue_date": "12-05-2026",
            },
        }

        def mock_answer_side_effect(question, records, st, preserve=False):
            st.append_turn(question, f"Mocked answer for {records[0]['title']}", records=records, active_notice=records[0])
            return f"Mocked answer for {records[0]['title']}"

        mock_grounded_answer.side_effect = mock_answer_side_effect

        state_wbjee = ConversationState()
        state_hostel = ConversationState()

        with patch("retrieve.retrieve_filtered_notices") as mock_filtered, \
             patch("retrieve.retrieve_context") as mock_context, \
             patch("Module4.main.retrieve_context", create=True) as mock_main_context, \
             patch("retrieve.retrieve_time_based") as mock_time_based:

            def retrieve_side_effect(question, **kwargs):
                if "wbjee" in str(question).lower():
                    return [notice_wbjee]
                return [notice_hostel]

            mock_filtered.side_effect = retrieve_side_effect
            mock_context.side_effect = retrieve_side_effect
            mock_main_context.side_effect = retrieve_side_effect
            mock_time_based.side_effect = retrieve_side_effect

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_wbjee = executor.submit(
                    ask_uniai, "What documents are required for WBJEE 2026?", state=state_wbjee
                )
                f_hostel = executor.submit(
                    ask_uniai, "Notice for hostel closure 2026", state=state_hostel
                )

                # Ensure exceptions are raised via future.result()
                ans_wbjee = f_wbjee.result()
                ans_hostel = f_hostel.result()

        self.assertIn("WBJEE", ans_wbjee)
        self.assertIn("Hostel", ans_hostel)

        # Assert zero cross-contamination of active notices
        self.assertEqual(state_wbjee.get_active_notice()["notice_id"], "notice_wbjee_101")
        self.assertEqual(state_hostel.get_active_notice()["notice_id"], "notice_hostel_202")

    @patch("app.ask_uniai")
    def test_fastapi_concurrent_sessions(self, mock_ask_uniai):
        """Verify that FastAPI /api/chat preserves session isolation concurrently."""
        from fastapi.testclient import TestClient
        from app import app, session_store

        client = TestClient(app)

        def mock_ask(question, state=None):
            name = "Alice" if "Alice" in question else "Bob"
            state.extract_and_remember_user_name(f"My name is {name}")
            return f"Answer for {name}"

        mock_ask_uniai.side_effect = mock_ask

        def send_request(cid, user):
            response = client.post(
                "/api/chat",
                json={"question": f"Hi, I am {user}", "conversation_id": cid},
            )
            return response.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(send_request, "cid-alice-123", "Alice")
            f2 = executor.submit(send_request, "cid-bob-456", "Bob")

            r1 = f1.result()
            r2 = f2.result()

        self.assertIn("Alice", r1["answer"])
        self.assertIn("Bob", r2["answer"])
        self.assertEqual(session_store["cid-alice-123"].get_user_name(), "Alice")
        self.assertEqual(session_store["cid-bob-456"].get_user_name(), "Bob")


if __name__ == "__main__":
    unittest.main()
