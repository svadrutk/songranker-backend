
import sys
import os
import random

# Add the project root to the python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.ranking import RankingManager

def simulate():
    # 1. Full Tracklist for Dangerous Woman (Standard + Deluxe/Target)
    all_songs = [
        "Moonlight",
        "Dangerous Woman",
        "Be Alright",
        "Into You",
        "Side to Side",
        "Let Me Love You",
        "Greedy",
        "Leave Me Lonely",
        "Everyday",
        "Sometimes",
        "I Don't Care",
        "Bad Decisions",
        "Touch It",
        "Knew Better / Forever Boy",
        "Thinking Bout You",
        "Step On Up",
        "Jason's Song (Gave It Away)",
        "Focus"
    ]
    
    # 2. User's Ideal Top 10 (Ordered)
    ideal_top_10 = [
        "Touch It",
        "Into You",
        "Everyday",
        "Greedy",
        "Dangerous Woman",
        "Sometimes",
        "Be Alright",
        "Side to Side",
        "Step On Up",
        "Bad Decisions"
    ]
    
    song_ids = {name: f"id_{i}" for i, name in enumerate(all_songs)}
    id_to_name = {v: k for k, v in song_ids.items()}
    
    comparisons = []
    
    # Simulate 50 duels - much less data
    print(f"Simulating 50 duels for {len(all_songs)} songs...")
    
    for _ in range(50):
        s1, s2 = random.sample(all_songs, 2)
        id1, id2 = song_ids[s1], song_ids[s2]
        
        is_s1_top = s1 in ideal_top_10
        is_s2_top = s2 in ideal_top_10
        
        comp = {"song_a_id": id1, "song_b_id": id2, "is_tie": False}
        
        if is_s1_top and is_s2_top:
            # Both are top songs -> higher ranked one wins
            idx1 = ideal_top_10.index(s1)
            idx2 = ideal_top_10.index(s2)
            comp["winner_id"] = id1 if idx1 < idx2 else id2
        elif is_s1_top:
            comp["winner_id"] = id1
        elif is_s2_top:
            comp["winner_id"] = id2
        else:
            # NEITHER is top -> User "doesn't care" (SKIP/Double Loss)
            comp["winner_id"] = None
            
        comparisons.append(comp)

    # 3. Run Bradley-Terry
    print("Running Bradley-Terry MM Algorithm...")
    results = RankingManager.compute_bradley_terry(list(song_ids.values()), comparisons)
    
    # 4. Sort and Print Results
    final_ranking = sorted(results.items(), key=lambda x: x[1], reverse=True)
    
    print("\n--- SIMULATION RESULTS ---")
    print(f"{'Rank':<5} | {'Song Name':<30} | {'BT Strength':<10}")
    print("-" * 60)
    for i, (sid, strength) in enumerate(final_ranking):
        name = id_to_name[sid]
        marker = f" [IDEAL #{ideal_top_10.index(name)+1}]" if name in ideal_top_10 else ""
        if name == "I Don't Care":
            marker = " [THE PROBLEM SONG]"
        print(f"{i+1:<5} | {name:<30} | {strength:.4f}{marker}")

if __name__ == "__main__":
    simulate()
