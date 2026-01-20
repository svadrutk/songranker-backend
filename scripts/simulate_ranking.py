
import sys
import os

# Add the project root to the python path so we can import the ranking manager
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.ranking import RankingManager

def simulate():
    # 1. Setup our "Ground Truth" (What we WANT the result to be)
    ideal_top_10 = [
        "Song 1 (Best)",
        "Song 2",
        "Song 3",
        "Song 4",
        "Song 5",
        "Song 6",
        "Song 7",
        "Song 8",
        "Song 9",
        "Song 10"
    ]
    
    # Other songs in the album we don't care about
    other_songs = [f"B-Side {i}" for i in range(1, 11)]
    all_songs = ideal_top_10 + other_songs
    song_ids = {name: f"id_{i}" for i, name in enumerate(all_songs)}
    id_to_name = {v: k for k, v in song_ids.items()}
    
    comparisons = []
    
    # 2. Simulate 200 Duels
    import random
    
    print(f"Simulating 200 duels for {len(all_songs)} songs...")
    
    for _ in range(200):
        # Pick two random songs
        s1, s2 = random.sample(all_songs, 2)
        id1, id2 = song_ids[s1], song_ids[s2]
        
        is_s1_top = s1 in ideal_top_10
        is_s2_top = s2 in ideal_top_10
        
        comp = {"song_a_id": id1, "song_b_id": id2}
        
        if is_s1_top and is_s2_top:
            # Both are top songs -> The higher ranked one wins
            idx1 = ideal_top_10.index(s1)
            idx2 = ideal_top_10.index(s2)
            comp["winner_id"] = id1 if idx1 < idx2 else id2
            comp["is_tie"] = False
        elif is_s1_top:
            # Only s1 is top -> s1 wins
            comp["winner_id"] = id1
            comp["is_tie"] = False
        elif is_s2_top:
            # Only s2 is top -> s2 wins
            comp["winner_id"] = id2
            comp["is_tie"] = False
        else:
            # NEITHER is top -> Simulation of "I don't care" (SKIP/Double Loss)
            comp["winner_id"] = None
            comp["is_tie"] = False
            
        comparisons.append(comp)

    # 3. Run Bradley-Terry
    print("Running Bradley-Terry MM Algorithm...")
    results = RankingManager.compute_bradley_terry(list(song_ids.values()), comparisons)
    
    # 4. Sort and Print Results
    final_ranking = sorted(results.items(), key=lambda x: x[1], reverse=True)
    
    print("\n--- SIMULATION RESULTS ---")
    print(f"{'Rank':<5} | {'Song Name':<20} | {'BT Strength':<10}")
    print("-" * 45)
    for i, (sid, strength) in enumerate(final_ranking):
        name = id_to_name[sid]
        marker = " [IDEAL]" if name in ideal_top_10 else ""
        print(f"{i+1:<5} | {name:<20} | {strength:.4f}{marker}")

if __name__ == "__main__":
    simulate()
