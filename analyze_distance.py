import json
import os
from collections import Counter

tasks_dir = 'tasks_nav'
distances = []

for filename in os.listdir(tasks_dir):
    if filename.startswith('nav_') and filename.endswith('.json'):
        filepath = os.path.join(tasks_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                if 'ground_truth' in data and 'optimal_distance_meters' in data['ground_truth']:
                    distances.append(data['ground_truth']['optimal_distance_meters'])
            except:
                pass

# Count distribution
counter = Counter(distances)
total = len(distances)

print("=" * 60)
print("NAV TASKS - optimal_distance_meters Distribution Analysis")
print("=" * 60)
print(f'\nTotal nav tasks analyzed: {total}')
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
print("Detailed Distribution (Individual Values):")
print("=" * 60)
print(f'{"Distance (m)":<15} {"Count":<10} {"Percentage":<10}')
print("-" * 50)
for dist in sorted(counter.keys()):
    count = counter[dist]
    pct = count / total * 100
    print(f'{dist:<15} {count:<10} {pct:.2f}%')
