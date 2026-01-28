
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app

class TestDecisionTimeAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.session_id = str(uuid4())
        self.song_a_id = str(uuid4())
        self.song_b_id = str(uuid4())

    @patch("app.api.v1.sessions.supabase_client")
    @patch("app.api.v1.sessions.task_queue")
    def test_decision_time_passed_to_db(self, mock_queue, mock_supabase):
        """
        Verify that decision_time_ms is correctly extracted from the request
        and passed to the database client.
        """
        # Mock Supabase responses
        mock_supabase.get_session_song_elos = AsyncMock(return_value=[
            {"song_id": self.song_a_id, "local_elo": 1500},
            {"song_id": self.song_b_id, "local_elo": 1500}
        ])
        
        mock_supabase.record_comparison_and_update_elo = AsyncMock(return_value=None)
        mock_supabase.get_session_comparison_count = AsyncMock(return_value=1)
        mock_supabase.get_session_details = AsyncMock(return_value={})

        decision_time = 1234
        payload = {
            "song_a_id": self.song_a_id,
            "song_b_id": self.song_b_id,
            "winner_id": self.song_a_id,
            "is_tie": False,
            "decision_time_ms": decision_time
        }

        # Call API
        response = self.client.post(f"/sessions/{self.session_id}/comparisons", json=payload)

        # Assertions
        self.assertEqual(response.status_code, 200, f"API failed with: {response.text}")
        
        # Verify call arguments
        mock_supabase.record_comparison_and_update_elo.assert_called_once()
        
        # Inspect the call arguments (args and kwargs)
        # Signature: (session_id, song_a_id, song_b_id, winner_id, is_tie, new_elo_a, new_elo_b, decision_time_ms=None)
        call_args = mock_supabase.record_comparison_and_update_elo.call_args
        
        # We check kwargs specifically since we passed it as a kwarg in the code
        # However, AsyncMock stores both.
        # Let's just check if 'decision_time_ms' is in kwargs and matches
        _, kwargs = call_args
        
        print(f"\nCall kwargs: {kwargs}")
        
        self.assertIn("decision_time_ms", kwargs)
        self.assertEqual(kwargs["decision_time_ms"], decision_time)
        
        print("✅ Success: decision_time_ms passed to DB client.")

if __name__ == "__main__":
    unittest.main()
