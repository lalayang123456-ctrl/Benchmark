"""
Analyze POI category distribution in navigation tasks.
Categories: restaurant, transit, landmark, service, gas_station, supermarket, other
"""

import json
import os
from collections import defaultdict

# Define category keywords
CATEGORIES = {
    'restaurant': [
        'restaurant', 'cafe', 'coffee', 'food', 'pizza', 'burger', 'grill', 'kitchen', 
        'diner', 'eatery', 'bakery', 'bar', 'pub', 'sushi', 'chicken', 'kebab', 'noodle',
        'thai', 'chinese', 'indian', 'mexican', 'italian', 'bistro', 'canteen', 'cafeteria',
        'buffet', 'steak', 'seafood', 'fish', 'chips', 'takeaway', 'fast food', 'kfc',
        'mcdonalds', "mcdonald's", 'subway', 'domino', 'papa john', 'taco', 'burrito', 'chippy', 'curry',
        'tandoori', 'biryani', 'dim sum', 'ramen', 'pho', 'teppanyaki', 'wok', 'dumpling',
        'hotpot', 'bbq', 'barbeque', 'rotisserie', 'deli', 'sandwich', 'panini', 'croissant',
        'patisserie', 'ice cream', 'gelato', 'frozen yogurt', 'smoothie', 'juice', 'tea house',
        'milk tea', 'boba', 'java', 'brew', 'roast', 'starbucks', 'costa', 'nero', 'pret',
        'greggs', 'krispy kreme', 'dunkin', 'wendy', 'five guys', 'nandos', "nando's",
        'wagamama', 'yo sushi', 'itsu', 'panda express', 'chipotle', 'shake shack',
        'chick-fil-a', 'popeyes', 'wimpy', 'steers', 'chicken licken', 'galito', 'debonairs',
        'ocean basket', 'spur', 'mugg & bean', 'vida e', 'seattle coffee', 'bootlegger'
    ],
    'transit': [
        'bus_station', 'bus station', 'transit_station', 'train', 'railway', 'metro', 'tram',
        'station', 'airport', 'terminal', 'bus stop', 'depot', 'platform', 'matatu', 'gare',
        'bahnhof', 'estacion', 'stazione'
    ],
    'landmark': [
        'monument', 'statue', 'museum', 'gallery', 'theatre', 'theater', 'cinema', 'stadium',
        'arena', 'park', 'garden', 'plaza', 'square', 'tower', 'castle', 'palace', 'cathedral',
        'mosque', 'temple', 'shrine', 'library', 'university', 'college', 'school', 'academy',
        'institute', 'hall', 'memorial', 'bridge', 'fountain', 'landmark', 'historic', 'heritage',
        'monument', 'masjid', 'minaret', 'chiesa', 'iglesia', 'kirche', 'eglise', 'basilica',
        'casa', 'palazzo', 'piazza', 'place', 'platz', 'ferris wheel', 'amusement', 'biblioteca',
        'parque', 'taman', 'gate'
    ],
    'service': [
        'bank', 'banque', 'banca', 'banco', 'raiffeisen', 'credit suisse', 'ubs', 'hsbc',
        'barclays', 'standard chartered', 'equity', 'kcb', 'cooperative', 'ncba', 'absa',
        'stanbic', 'dtb', 'i&m', 'family bank', 'atm', 'pharmacy', 'pharmacie', 'farmacia',
        'apotheke', 'chemist', 'apotheek', 'hospital', 'hopital', 'krankenhaus', 'ospedale', 'clinic',
        'doctor', 'dentist', 'health', 'medical', 'police', 'polizia', 'polizei', 'gendarmerie',
        'fire station', 'pompier', 'feuerwehr', 'post_office', 'post office', 'poste', 'correo',
        'ufficio postale', 'hotel', 'motel', 'hostel', 'lodging', 'inn', 'spa', 'salon', 'barber',
        'laundry', 'dry clean', 'repair', 'mechanic', 'garage', 'car wash', 'insurance',
        'lawyer', 'attorney', 'accountant', 'consultant', 'agency', 'embassy', 'consulate',
        'government', 'court', 'town hall', 'city hall', 'council', 'church', 'parking',
        'gym', 'fitness', 'yoga', 'swimming', 'sport', 'recreation', 'dispensary', 'diagnostic',
        'lab', 'laboratory', 'information', 'info', 'gereja', 'smpk', 'sma', 'universitas'
    ],
    'gas_station': [
        'gas_station', 'gas station', 'petrol', 'fuel', 'shell', 'esso', 'texaco', 'mobil',
        'chevron', 'total', 'filling station', 'service station', 'oilibya', 'rubis', 'kobil',
        'kenol', 'galana', 'hashi', 'gulf energy', 'national oil', 'tosha', 'engen', 'caltex',
        'astrol', 'vivo energy', 'oryx', 'libya oil', 'stabex', 'tankstelle', 'gasolinera',
        'distributore', 'station-service', 'essence', 'benzina', 'gasolina', 'emarat', 'adnoc',
        'woqod', 'enoc', 'eppco', 'bp'
    ],
    'supermarket': [
        'supermarket', 'supermarche', 'supermercado', 'supermercato', 'supermarkt',
        'grocery', 'market', 'marche', 'mercado', 'mercato', 'markt', 'mart', 'hypermarket',
        'carrefour', 'tesco', 'sainsbury', 'asda', 'lidl', 'aldi', 'costco', 'walmart', 'target',
        'naivas', 'quickmart', 'quick mart', 'chandarana', 'nakumatt', 'tuskeys', 'tusky',
        'khetia', 'foodplus', 'food plus', 'greenmart', 'cleanshelf', 'mulleys', 'eastmatt',
        'maathai', 'uchumi', 'shoprite', 'game', 'pick n pay', 'spar', 'choppies',
        'migros', 'coop', 'denner', 'volg', 'manor', 'globus', 'rewe', 'edeka', 'netto',
        'kaufland', 'penny', 'leclerc', 'auchan', 'intermarche', 'casino', 'monoprix',
        'franprix', 'simply', 'conad', 'esselunga', 'pam', 'despar', 'eurospin',
        'woolworths', 'checkers', 'food lover', 'indomaret', 'alfamart', '7-eleven',
        'seven eleven', 'lawson', 'circle k', 'family mart', 'conveni', 'kiosk'
    ]
}


def categorize_poi(target_name):
    """Categorize a POI based on its name."""
    if not target_name:
        return 'other'
    name_lower = target_name.strip().lower()
    
    # Check each category
    for category, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword in name_lower:
                return category
    return 'other'


def analyze_nav_tasks(tasks_dir):
    """Analyze all navigation tasks and return POI distribution."""
    poi_counts = defaultdict(int)
    poi_examples = defaultdict(list)
    all_others = []
    
    for filename in os.listdir(tasks_dir):
        if filename.startswith('nav_') and filename.endswith('.json'):
            filepath = os.path.join(tasks_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    task = json.load(f)
                
                if 'ground_truth' in task and 'target_name' in task['ground_truth']:
                    target_name = task['ground_truth']['target_name']
                    category = categorize_poi(target_name)
                    poi_counts[category] += 1
                    if len(poi_examples[category]) < 5:
                        poi_examples[category].append(target_name)
                    if category == 'other':
                        all_others.append(target_name)
            except Exception as e:
                print(f'Error reading {filename}: {e}')
    
    return poi_counts, poi_examples, all_others


def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    tasks_dir = os.path.join(current_dir, 'tasks')
    
    print("Analyzing POI distribution in navigation tasks...")
    poi_counts, poi_examples, all_others = analyze_nav_tasks(tasks_dir)
    
    # Calculate totals
    total = sum(poi_counts.values())
    
    print(f'\n{"="*80}')
    print(f' POI Category Distribution in Nav Tasks')
    print(f'{"="*80}')
    print(f' Total nav tasks analyzed: {total}')
    print(f'{"="*80}\n')
    
    # Sort by count descending
    sorted_categories = sorted(poi_counts.items(), key=lambda x: -x[1])
    
    # Print header
    print(f'{"Category":<15} | {"Count":<8} | {"Percentage":<10} | {"Examples"}')
    print('-' * 80)
    
    for category, count in sorted_categories:
        percentage = (count / total * 100) if total > 0 else 0
        examples = ', '.join(poi_examples[category][:3])
        if len(examples) > 40:
            examples = examples[:37] + '...'
        try:
            print(f'{category:<15} | {count:<8} | {percentage:>6.1f}%    | {examples}')
        except UnicodeEncodeError:
            print(f'{category:<15} | {count:<8} | {percentage:>6.1f}%    | [Special Characters in Examples]')
    
    print('-' * 80)
    print(f'{"TOTAL":<15} | {total:<8} | {"100.0%":<10}')
    print()
    
    # Show some "other" examples for review
    if all_others:
        print(f'\n{"="*80}')
        print(f' Sample of "other" category POIs (for potential reclassification):')
        print(f'{"="*80}')
        for name in all_others[:20]:
            try:
                print(f'  - {name}')
            except UnicodeEncodeError:
                print(f'  - [Unprintable Name]')
        if len(all_others) > 20:
            print(f'  ... and {len(all_others) - 20} more')


if __name__ == '__main__':
    main()
