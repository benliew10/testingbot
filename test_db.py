import json
import os
import db

def main():
    """Test database functionality"""
    print("Testing database...")
    
    # Check if database file exists
    if os.path.exists(db.DB_FILE):
        print(f"Database file exists: {db.DB_FILE}")
        
        # Load database
        try:
            with open(db.DB_FILE, "r") as f:
                data = json.load(f)
                print(f"Database content: {json.dumps(data, indent=2)}")
        except Exception as e:
            print(f"Error loading database: {e}")
    else:
        print(f"Database file does not exist: {db.DB_FILE}")
        print("Creating sample database...")
        
        # Create sample database
        db.add_image("img_1", 100, "test_file_id_1")
        db.add_image("img_2", 200, "test_file_id_2")
        
        print("Sample images added.")
    
    # Check images
    images = db.get_all_images()
    print(f"Total images: {len(images)}")
    
    for img in images:
        print(f"Image: {img['image_id']}, Number: {img['number']}, Status: {img['status']}")
    
    # Count open and closed images
    open_count, closed_count = db.count_images_by_status()
    print(f"Open images: {open_count}")
    print(f"Closed images: {closed_count}")
    
    # Get random open image
    open_image = db.get_random_open_image()
    if open_image:
        print(f"Random open image: {open_image['image_id']}")
    else:
        print("No open images found.")

if __name__ == "__main__":
    main() 