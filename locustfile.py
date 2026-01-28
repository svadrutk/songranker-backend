import random
from locust import HttpUser, task, between

class SongRankerUser(HttpUser):
    # Faster wait time to generate more load
    wait_time = between(0.1, 0.5)

    @task(5)
    def search_and_view(self):
        """Search for an artist and then view a random album's tracks."""
        artists = ["Taylor Swift", "The Beatles", "Radiohead", "Kendrick Lamar", "Daft Punk"]
        query = random.choice(artists)
        
        # 1. Search
        response = self.client.get(f"/search?query={query}", name="/search")
        if response.status_code == 200:
            results = response.json()
            if results:
                # 2. Pick a random album and get tracks
                album = random.choice(results)
                album_id = album.get("id")
                if album_id:
                    self.client.get(f"/tracks/{album_id}", name="/tracks/[id]")

    @task(1)
    def health_check(self):
        self.client.get("/health", name="/health")
