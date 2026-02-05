import cv2
import os
import numpy as np
from pathlib import Path

def is_black_bottom(image_path, intensity_threshold=20, black_pixel_threshold=0.8, bottom_ratio=0.05):
    """
    Checks if the bottom section of the image is mostly black.
    
    Args:
        image_path: Path to the image file.
        intensity_threshold: Pixel intensity threshold to consider as 'black' (0-255).
        black_pixel_threshold: Minimum percentage of black pixels to flag (0-1).
        bottom_ratio: Ratio of the image from the bottom to check (0.05 means bottom 5%).
        
    Returns:
        True if detected as black bottom, False otherwise.
    """
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            print(f"Warning: Could not read {image_path}")
            return False
            
        h, w, _ = img.shape
        start_h = int(h * (1 - bottom_ratio))
        
        # Crop the bottom section
        bottom_section = img[start_h:, :]
        
        # Convert to grayscale for easier analysis
        gray = cv2.cvtColor(bottom_section, cv2.COLOR_BGR2GRAY)
        
        # Count pixels that are very dark (close to black)
        black_pixels = np.sum(gray < intensity_threshold)
        total_pixels = gray.size
        black_ratio = black_pixels / total_pixels
        
        # If a high percentage of pixels are black, flag it
        if black_ratio >= black_pixel_threshold:
            return True
            
        return False
        
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return False

def main():
    # Define paths
    ROOT_DIR = Path(__file__).parent.parent
    PANOS_DIR = ROOT_DIR / "data" / "panoramas"
    OUTPUT_FILE = ROOT_DIR / "scripts" / "black_bottom_panos.txt"
    
    print(f"Scanning directory: {PANOS_DIR}")
    
    if not PANOS_DIR.exists():
        print(f"Error: Directory {PANOS_DIR} does not exist.")
        return

    black_bottom_ids = []
    
    # List all jpg files
    files = list(PANOS_DIR.glob("*.jpg"))
    total_files = len(files)
    print(f"Found {total_files} images.")
    
    for i, file_path in enumerate(files):
        if i % 100 == 0:
            print(f"Processed {i}/{total_files}...")
            
        if is_black_bottom(file_path):
            pano_id = file_path.stem
            black_bottom_ids.append(pano_id)
            print(f"Detected: {pano_id}")
            
    print("-" * 30)
    print(f"Scan complete. Found {len(black_bottom_ids)} black-bottom panoramas.")
    
    # Save to file
    with open(OUTPUT_FILE, "w") as f:
        for pid in black_bottom_ids:
            f.write(f"{pid}\n")
            
    print(f"Saved list to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
