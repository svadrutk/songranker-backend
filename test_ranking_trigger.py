
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi.testclient import TestClient

# Mock the dependencies BEFORE importing the app if possible, 
# or patch them after import.
# Since app.main imports app.api.v1.sessions which imports supabase_client,
# we need to be careful. Patching is safer.

from app.main import app

class TestRankingTrigger(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.session_id = str(uuid4())
        self.song_a_id = str(uuid4())
        self.song_b_id = str(uuid4())

    @patch("app.api.v1.sessions.supabase_client")
    @patch("app.api.v1.sessions.task_queue")
    def test_ranking_trigger_on_5th_duel(self, mock_queue, mock_supabase):
        """
        Verify that recording the 5th comparison triggers the background ranking task.
        """
        # Mock Supabase responses
        # 1. get_session_song_elos: Return some default elos
        mock_supabase.get_session_song_elos = AsyncMock(return_value=[
            {"song_id": self.song_a_id, "local_elo": 1500},
            {"song_id": self.song_b_id, "local_elo": 1500}
        ])
        
        # 2. record_comparison_and_update_elo: succeed
        mock_supabase.record_comparison_and_update_elo = AsyncMock(return_value=None)
        
        # 3. get_session_comparison_count: Return 5 to trigger logic
        mock_supabase.get_session_comparison_count = AsyncMock(return_value=5)

        # Payload
        payload = {
            "song_a_id": self.song_a_id,
            "song_b_id": self.song_b_id,
            "winner_id": self.song_a_id,
            "is_tie": False
        }

        # Call API
        response = self.client.post(f"/sessions/{self.session_id}/comparisons", json=payload)

        # Assertions
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        print(f"\nAPI Response: {data}")
        
        self.assertTrue(data["success"])
        self.assertTrue(data["sync_queued"], "sync_queued should be True on 5th duel")
        
        # Verify queue enqueue was called
        mock_queue.enqueue.assert_called_once()
        args, _ = mock_queue.enqueue.call_args
        # Check that the function passed is run_ranking_update and arg is session_id
        from app.tasks import run_ranking_update
        self.assertEqual(args[0], run_ranking_update)
        self.assertEqual(args[1], self.session_id)
        
        print("✅ Success: Ranking update queued on 5th duel.")

    @patch("app.api.v1.sessions.supabase_client")
    @patch("app.api.v1.sessions.task_queue")
    def test_ranking_no_trigger_on_4th_duel(self, mock_queue, mock_supabase):
        """
        Verify that recording the 4th comparison DOES NOT trigger the task.
        """
        mock_supabase.get_session_song_elos = AsyncMock(return_value=[
            {"song_id": self.song_a_id, "local_elo": 1500},
            {"song_id": self.song_b_id, "local_elo": 1500}
        ])
        mock_supabase.record_comparison_and_update_elo = AsyncMock(return_value=None)
        
        # Return 4 (not divisible by 5)
        mock_supabase.get_session_comparison_count = AsyncMock(return_value=4)

        payload = {
            "song_a_id": self.song_a_id,
            "song_b_id": self.song_b_id,
            "winner_id": self.song_a_id,
            "is_tie": False
        }

        response = self.client.post(f"/sessions/{self.session_id}/comparisons", json=payload)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertFalse(data["sync_queued"], "sync_queued should be False on 4th duel")
        mock_queue.enqueue.assert_not_called()
        
        print("✅ Success: Ranking update skipped on 4th duel.")

if __name__ == "__main__":
    unittest.main()
