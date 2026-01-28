"""
Quick test for fix_reverse_headings() method.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator.link_enhancer import LinkEnhancer

# Test case: A->B heading=90, B->A heading=90 (should be 270)
test_data = {
    'A': {
        'lat': 40.0, 
        'lng': -73.0, 
        'links': [{'panoId': 'B', 'heading': 90}]
    }, 
    'B': {
        'lat': 40.0, 
        'lng': -73.001, 
        'links': [{'panoId': 'A', 'heading': 90}]  # Wrong! Should be 270
    }
}

print("Before fix:")
print(f"  A->B heading: {test_data['A']['links'][0]['heading']}")
print(f"  B->A heading: {test_data['B']['links'][0]['heading']}")

enhancer = LinkEnhancer()
result, count = enhancer.fix_reverse_headings(test_data)

print(f"\nFixes applied: {count}")
print(f"\nAfter fix:")
print(f"  A->B heading: {result['A']['links'][0]['heading']}")
print(f"  B->A heading: {result['B']['links'][0]['heading']}")

# Verify
expected_reverse = (90 + 180) % 360  # = 270
actual = result['B']['links'][0]['heading']
print(f"\nExpected B->A: {expected_reverse}")
print(f"Actual B->A: {actual}")
print(f"Test PASSED!" if actual == expected_reverse else "Test FAILED!")
