import json
import os
from collections import Counter

tasks_dir = 'tasks_perception'
distances = []

for filename in os.listdir(tasks_dir):
    if filename.startswith('dis_') and filename.endswith('.json'):
        filepath = os.path.join(tasks_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if 'ground_truth' in data and 'distance_between_pois_m' in data['ground_truth']:
                    distances.append(data['ground_truth']['distance_between_pois_m'])
            except:
                pass

if not distances:
    print("No distances found.")
    exit()

# Count distribution
counter = Counter(distances)
total = len(distances)

print("=" * 60)
print("PERCEPTION TASKS (dis) - distance_between_pois_m Analysis")
print("=" * 60)
print(f'\nTotal perception tasks analyzed: {total}')
print()

# Summary statistics
print("Summary Statistics:")
print("-" * 40)
print(f"  Min distance: {min(distances)} m")
print(f"  Max distance: {max(distances)} m")
print(f"  Mean distance: {sum(distances)/len(distances):.1f} m")
sorted_distances = sorted(distances)
median = sorted_distances[len(sorted_distances)//2]
print(f"  Median distance: {median} m")
print()

# Group by ranges
ranges = [
    (0, 50, "0-50m"),
    (51, 100, "51-100m"),
    (101, 150, "101-150m"),
    (151, 200, "151-200m"),
    (201, 250, "201-250m"),
    (251, 300, "251-300m"),
    (301, 400, "301-400m"),
    (401, 500, "401-500m"),
    (501, 1000, "501-1000m"),
    (1001, float('inf'), ">1000m"),
]

print("Distribution by Distance Ranges:")
print("-" * 50)
print(f'{"Range":<15} {"Count":<10} {"Percentage":<10}')
print("-" * 50)

for low, high, label in ranges:
    count = sum(1 for d in distances if low <= d <= high)
    pct = count / total * 100
    print(f'{label:<15} {count:<10} {pct:.2f}%')

print()
print("=" * 60)
print()
print("=" * 60)
print("Tasks with distance > 200m:")
print("=" * 60)
tasks_over_200 = []

for filename in os.listdir(tasks_dir):
    if filename.startswith('dis_') and filename.endswith('.json'):
        filepath = os.path.join(tasks_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if 'ground_truth' in data and 'distance_between_pois_m' in data['ground_truth']:
                    dist = data['ground_truth']['distance_between_pois_m']
                    if dist > 150:
                        tasks_over_200.append((data['task_id'], dist))
            except:
                pass

# Sort by distance
tasks_over_200.sort(key=lambda x: x[1])

print(f'{"Task ID":<40} {"Distance (m)":<10}')
print("-" * 50)
for task_id, dist in tasks_over_200:
    print(f'{task_id:<40} {dist:.1f}')
