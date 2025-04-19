#!/usr/bin/env python3
import db
import json
import random
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Update these with your Group B chat IDs
GROUP_B_IDS = [-1002648811668, -4777804394]

def distribute_images():
    """Distribute images evenly between Group B chats."""
    # Get all images
    images = db.get_all_images()
    if not images:
        logger.info("No images found in database")
        return
    
    logger.info(f"Found {len(images)} images in database")
    
    # Count how many images were updated
    updated_count = 0
    
    # Distribute images between the Group B chats
    for i, img in enumerate(images):
        image_id = img['image_id']
        
        # Assign Group B chat based on alternating index
        target_group_b = GROUP_B_IDS[i % len(GROUP_B_IDS)]
        
        # Create or update metadata
        metadata = {}
        if 'metadata' in img and img['metadata']:
            if isinstance(img['metadata'], dict):
                metadata = img['metadata']
            else:
                try:
                    metadata = json.loads(img['metadata'])
                except:
                    metadata = {}
        
        # Set the source_group_b_id
        metadata['source_group_b_id'] = target_group_b
        
        # Update the image metadata
        success = db.update_image_metadata(image_id, json.dumps(metadata))
        if success:
            updated_count += 1
            logger.info(f"Updated image {image_id} to use Group B: {target_group_b}")
        else:
            logger.error(f"Failed to update image {image_id}")
    
    logger.info(f"Successfully updated {updated_count} out of {len(images)} images")

if __name__ == "__main__":
    distribute_images() 