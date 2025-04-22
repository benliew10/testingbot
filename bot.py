import logging
import os
import re
import json
import time
from typing import Dict, Optional, List, Any
from datetime import datetime

from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.error import NetworkError, TimedOut, RetryAfter

import db

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = "7638451592:AAE9Ux_MFWFpzIKnUscX_-7QVsaW6QwTXCM"

# Group IDs
# Moving from single group to multiple groups
GROUP_A_IDS = set()  # Set of Group A chat IDs
GROUP_B_IDS = set()  # Set of Group B chat IDs

# Legacy variables for backward compatibility
GROUP_A_ID = -4687450746  # Using negative ID for group chats
GROUP_B_ID = -1002648811668  # New supergroup ID from migration message

# Initialize default groups if needed
if not GROUP_A_IDS:
    GROUP_A_IDS.add(GROUP_A_ID)
if not GROUP_B_IDS:
    GROUP_B_IDS.add(GROUP_B_ID)

# Admin system
GLOBAL_ADMINS = set([5962096701, 1844353808, 7997704196, 5965182828])  # Global admins with full permissions
GROUP_ADMINS = {}  # Format: {chat_id: set(user_ids)} - Group-specific admins

# Message forwarding control
FORWARDING_ENABLED = True  # Controls if messages can be forwarded from Group B to Group A

# Paths for persistent storage
FORWARDED_MSGS_FILE = "forwarded_msgs.json"
GROUP_B_RESPONSES_FILE = "group_b_responses.json"
GROUP_A_IDS_FILE = "group_a_ids.json"
GROUP_B_IDS_FILE = "group_b_ids.json"
GROUP_ADMINS_FILE = "group_admins.json"
PENDING_CUSTOM_AMOUNTS_FILE = "pending_custom_amounts.json"
SETTINGS_FILE = "bot_settings.json"

# Message IDs mapping for forwarded messages
forwarded_msgs: Dict[str, Dict] = {}

# Store Group B responses for each image
group_b_responses: Dict[str, str] = {}

# Store pending requests that need approval
pending_requests: Dict[int, Dict] = {}

# Store pending custom amount approvals from Group B
pending_custom_amounts: Dict[int, Dict] = {}  # Format: {message_id: {img_id, amount, responder, original_msg_id}}

# Function to safely send messages with retry logic
def safe_send_message(context, chat_id, text, reply_to_message_id=None, max_retries=3, retry_delay=2):
    """Send a message with retry logic to handle network errors."""
    for attempt in range(max_retries):
        try:
            return context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to_message_id
            )
        except (NetworkError, TimedOut, RetryAfter) as e:
            logger.warning(f"Network error on attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Increase delay for next retry
                retry_delay *= 1.5
            else:
                logger.error(f"Failed to send message after {max_retries} attempts")
                raise

# Function to safely reply to a message with retry logic
def safe_reply_text(update, text, max_retries=3, retry_delay=2):
    """Reply to a message with retry logic to handle network errors."""
    for attempt in range(max_retries):
        try:
            return update.message.reply_text(text)
        except (NetworkError, TimedOut, RetryAfter) as e:
            logger.warning(f"Network error on attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Increase delay for next retry
                retry_delay *= 1.5
            else:
                logger.error(f"Failed to reply to message after {max_retries} attempts")
                # Just log the error but don't crash the handler
                return None

# Function to save all configuration data
def save_config_data():
    """Save all configuration data to files."""
    # Save Group A IDs
    try:
        with open(GROUP_A_IDS_FILE, 'w') as f:
            json.dump(list(GROUP_A_IDS), f, indent=2)
            logger.info(f"Saved {len(GROUP_A_IDS)} Group A IDs to file")
    except Exception as e:
        logger.error(f"Error saving Group A IDs: {e}")
    
    # Save Group B IDs
    try:
        with open(GROUP_B_IDS_FILE, 'w') as f:
            json.dump(list(GROUP_B_IDS), f, indent=2)
            logger.info(f"Saved {len(GROUP_B_IDS)} Group B IDs to file")
    except Exception as e:
        logger.error(f"Error saving Group B IDs: {e}")
    
    # Save Group Admins
    try:
        # Convert sets to lists for JSON serialization
        admins_json = {str(chat_id): list(user_ids) for chat_id, user_ids in GROUP_ADMINS.items()}
        with open(GROUP_ADMINS_FILE, 'w') as f:
            json.dump(admins_json, f, indent=2)
            logger.info(f"Saved group admins to file")
    except Exception as e:
        logger.error(f"Error saving group admins: {e}")
    
    # Save Bot Settings
    try:
        settings = {
            "forwarding_enabled": FORWARDING_ENABLED
        }
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
            logger.info(f"Saved bot settings to file")
    except Exception as e:
        logger.error(f"Error saving bot settings: {e}")

# Function to load all configuration data
def load_config_data():
    """Load all configuration data from files."""
    global GROUP_A_IDS, GROUP_B_IDS, GROUP_ADMINS, FORWARDING_ENABLED
    
    # Load Group A IDs
    if os.path.exists(GROUP_A_IDS_FILE):
        try:
            with open(GROUP_A_IDS_FILE, 'r') as f:
                # Convert all IDs to integers
                GROUP_A_IDS = set(int(x) for x in json.load(f))
                logger.info(f"Loaded {len(GROUP_A_IDS)} Group A IDs from file")
        except Exception as e:
            logger.error(f"Error loading Group A IDs: {e}")
    
    # Load Group B IDs
    if os.path.exists(GROUP_B_IDS_FILE):
        try:
            with open(GROUP_B_IDS_FILE, 'r') as f:
                # Convert all IDs to integers
                GROUP_B_IDS = set(int(x) for x in json.load(f))
                logger.info(f"Loaded {len(GROUP_B_IDS)} Group B IDs from file")
        except Exception as e:
            logger.error(f"Error loading Group B IDs: {e}")
    
    # Load Group Admins
    if os.path.exists(GROUP_ADMINS_FILE):
        try:
            with open(GROUP_ADMINS_FILE, 'r') as f:
                admins_json = json.load(f)
                # Convert keys back to integers and values back to sets
                GROUP_ADMINS = {int(chat_id): set(user_ids) for chat_id, user_ids in admins_json.items()}
                logger.info(f"Loaded group admins from file")
        except Exception as e:
            logger.error(f"Error loading group admins: {e}")
    
    # Load Bot Settings
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                FORWARDING_ENABLED = settings.get("forwarding_enabled", True)
                logger.info(f"Loaded bot settings: forwarding_enabled={FORWARDING_ENABLED}")
        except Exception as e:
            logger.error(f"Error loading bot settings: {e}")

# Check if user is a global admin
def is_global_admin(user_id):
    """Check if user is a global admin."""
    return user_id in GLOBAL_ADMINS

# Check if user is a group admin for a specific chat
def is_group_admin(user_id, chat_id):
    """Check if user is a group admin for a specific chat."""
    # Global admins are also group admins
    if is_global_admin(user_id):
        return True
    
    # Check if user is in the group admin list for this chat
    return chat_id in GROUP_ADMINS and user_id in GROUP_ADMINS.get(chat_id, set())

# Add group admin
def add_group_admin(user_id, chat_id):
    """Add a user as a group admin for a specific chat."""
    if chat_id not in GROUP_ADMINS:
        GROUP_ADMINS[chat_id] = set()
    
    GROUP_ADMINS[chat_id].add(user_id)
    save_config_data()
    logger.info(f"Added user {user_id} as group admin for chat {chat_id}")

# Load persistent data on startup
def load_persistent_data():
    global forwarded_msgs, group_b_responses, pending_custom_amounts
    
    # Load forwarded_msgs
    if os.path.exists(FORWARDED_MSGS_FILE):
        try:
            with open(FORWARDED_MSGS_FILE, 'r') as f:
                forwarded_msgs = json.load(f)
                logger.info(f"Loaded {len(forwarded_msgs)} forwarded messages from file")
        except Exception as e:
            logger.error(f"Error loading forwarded messages: {e}")
    
    # Load group_b_responses
    if os.path.exists(GROUP_B_RESPONSES_FILE):
        try:
            with open(GROUP_B_RESPONSES_FILE, 'r') as f:
                group_b_responses = json.load(f)
                logger.info(f"Loaded {len(group_b_responses)} Group B responses from file")
        except Exception as e:
            logger.error(f"Error loading Group B responses: {e}")
    
    # Load pending_custom_amounts
    if os.path.exists(PENDING_CUSTOM_AMOUNTS_FILE):
        try:
            with open(PENDING_CUSTOM_AMOUNTS_FILE, 'r') as f:
                # Convert string keys back to integers
                data = json.load(f)
                pending_custom_amounts = {int(k): v for k, v in data.items()}
                logger.info(f"Loaded {len(pending_custom_amounts)} pending custom amounts from file")
        except Exception as e:
            logger.error(f"Error loading pending custom amounts: {e}")
    
    # Load configuration data
    load_config_data()

# Save persistent data
def save_persistent_data():
    # Save forwarded_msgs
    try:
        with open(FORWARDED_MSGS_FILE, 'w') as f:
            json.dump(forwarded_msgs, f, indent=2)
            logger.info(f"Saved {len(forwarded_msgs)} forwarded messages to file")
    except Exception as e:
        logger.error(f"Error saving forwarded messages: {e}")
    
    # Save group_b_responses
    try:
        with open(GROUP_B_RESPONSES_FILE, 'w') as f:
            json.dump(group_b_responses, f, indent=2)
            logger.info(f"Saved {len(group_b_responses)} Group B responses to file")
    except Exception as e:
        logger.error(f"Error saving Group B responses: {e}")
    
    # Save pending_custom_amounts
    try:
        with open(PENDING_CUSTOM_AMOUNTS_FILE, 'w') as f:
            json.dump(pending_custom_amounts, f, indent=2)
            logger.info(f"Saved {len(pending_custom_amounts)} pending custom amounts to file")
    except Exception as e:
        logger.error(f"Error saving pending custom amounts: {e}")

def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user_id = update.effective_user.id
    is_admin = is_global_admin(user_id)
    
    welcome_message = "欢迎使用TLG群组管理机器人！"
    
    # Show admin controls if user is admin and in private chat
    if is_admin and update.effective_chat.type == "private":
        admin_controls = (
            "\n\n管理员控制:\n"
            "• 开启转发 - 开启群B到群A的消息转发\n"
            "• 关闭转发 - 关闭群B到群A的消息转发\n"
            "• 转发状态 - 切换转发状态\n"
            "• /debug - 显示当前状态信息"
        )
        welcome_message += admin_controls
    
    update.message.reply_text(welcome_message)

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 Bot Commands:\n\n"
        "🚀 /start - Start the bot\n"
        "❓ /help - Show this help message\n"
        "🖼️ /setimage <number> - Set an image with a number (reply to an image)\n"
        "📋 /images - List all images and their statuses\n"
        "🔍 /debug - Show bot status\n\n"
        "👑 Admin functionality:\n"
        "- Reply to a user's message with the word '群' to send them an image"
    )
    update.message.reply_text(help_text)

def set_image(update: Update, context: CallbackContext) -> None:
    """Set an image with a number."""
    # Check if admin (can be customized)
    if update.effective_chat.type != "private":
        return
    
    # Check if replying to an image
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        update.message.reply_text("Please reply to an image with this command.")
        return
    
    # Check if number provided
    if not context.args:
        update.message.reply_text("Please provide a number for this image.")
        return
    
    try:
        number = int(context.args[0])
    except ValueError:
        update.message.reply_text("Please provide a valid number.")
        return
    
    # Get the file_id of the image
    file_id = update.message.reply_to_message.photo[-1].file_id
    image_id = f"img_{len(db.get_all_images()) + 1}"
    
    if db.add_image(image_id, number, file_id):
        update.message.reply_text(f"Image set with number {number} and status 'open'.")
    else:
        update.message.reply_text("Failed to set image. It might already exist.")

def list_images(update: Update, context: CallbackContext) -> None:
    """List all available images with their statuses and associated Group B."""
    user_id = update.effective_user.id
    
    # Only allow admins
    if not is_global_admin(user_id):
        update.message.reply_text("Only global admins can use this command.")
        return
    
    images = db.get_all_images()
    if not images:
        update.message.reply_text("No images available.")
        return
    
    # Format the list of images
    image_list = []
    for img in images:
        status = img['status']
        number = img['number']
        image_id = img['image_id']
        
        # Get Group B ID from metadata if available
        group_b_id = "none"
        if 'metadata' in img and isinstance(img['metadata'], dict):
            group_b_id = img['metadata'].get('source_group_b_id', "none")
        
        image_list.append(f"🔢 Group: {number} | 🆔 ID: {image_id} | ⚡ Status: {status} | 🔸 Group B: {group_b_id}")
    
    # Join the list with newlines
    message = "📋 Available Images:\n\n" + "\n\n".join(image_list)
    
    # Add instructions for updating Group B association
    message += "\n\n🔄 To update Group B association:\n/setimagegroup <image_id> <group_b_id>"
    
    update.message.reply_text(message)

# Define a helper function for consistent Group B mapping
def get_group_b_for_image(image_id, metadata=None):
    """Get the consistent Group B ID for an image."""
    # If metadata has a source_group_b_id and it's valid, use it
    if isinstance(metadata, dict) and 'source_group_b_id' in metadata:
        try:
            # Convert to int to ensure consistent comparison
            source_group_b_id = int(metadata['source_group_b_id'])
            
            # Check if source_group_b_id is valid - all Group B IDs are already integers
            if source_group_b_id in GROUP_B_IDS or source_group_b_id == GROUP_B_ID:
                logger.info(f"Using existing Group B mapping for image {image_id}: {source_group_b_id}")
                return source_group_b_id
            else:
                logger.warning(f"Source Group B ID {source_group_b_id} is not in valid Group B IDs: {GROUP_B_IDS}")
        except (ValueError, TypeError) as e:
            logger.error(f"Error converting source_group_b_id to int: {e}. Metadata: {metadata}")
    
    # Create a deterministic mapping
    # Use a hash of the image ID to ensure the same image always goes to the same Group B
    image_hash = hash(image_id)
    
    # Get available Group B IDs
    available_group_bs = list(GROUP_B_IDS) if GROUP_B_IDS else [GROUP_B_ID]
    
    # Deterministically select a Group B based on image hash
    if available_group_bs:
        selected_index = abs(image_hash) % len(available_group_bs)
        target_group_b_id = available_group_bs[selected_index]  # Already an integer
        
        logger.info(f"Created deterministic mapping for image {image_id} to Group B {target_group_b_id}")
        
        # Save this mapping for future use
        updated_metadata = metadata.copy() if isinstance(metadata, dict) else {}
        updated_metadata['source_group_b_id'] = target_group_b_id
        db.update_image_metadata(image_id, json.dumps(updated_metadata))
        logger.info(f"Saved Group B mapping to image metadata: {updated_metadata}")
        
        return target_group_b_id
    else:
        logger.error("No available Group B IDs!")
        # Default to GROUP_B_ID if no other options
        return GROUP_B_ID

def handle_group_a_message(update: Update, context: CallbackContext) -> None:
    """Handle messages in Group A."""
    # Add debug logging
    chat_id = update.effective_chat.id
    logger.info(f"Received message in chat ID: {chat_id}")
    
    # Check if this chat is a Group A - ensure we're comparing integers
    if int(chat_id) not in GROUP_A_IDS and int(chat_id) != GROUP_A_ID:
        logger.info(f"Message received in non-Group A chat: {chat_id}")
        return
    
    # Get message text
    text = update.message.text.strip()
    logger.info(f"Received message: {text}")
    
    # Skip messages that start with "+"
    if text.startswith("+"):
        logger.info("Message starts with '+', skipping")
        return
    
    # Try to match "{number} 群" format first
    match = re.search(r'^(\d+)\s*群$', text)
    
    # If no match, check if it's just a pure number
    if not match and text.isdigit():
        logger.info(f"Pure number format detected: {text}")
        amount = text
    elif match:
        logger.info(f"'{number} 群' format detected")
        amount = match.group(1)
    else:
        logger.info("Message doesn't match any accepted format")
        return
    
    logger.info(f"Matched amount: {amount}")
    
    # Check if the number is between 100 and 200 (inclusive)
    try:
        amount_int = int(amount)
        if amount_int < 100 or amount_int > 200:
            logger.info(f"Number {amount} is outside the allowed range (100-200).")
            return
    except ValueError:
        logger.info(f"Invalid number format: {amount}")
        return
    
    # Check if we have any images
    images = db.get_all_images()
    if not images:
        logger.info("No images found in database - remaining silent")
        # Removed the reply message to remain silent when no images are set
        return
        
    # Count open and closed images
    open_count, closed_count = db.count_images_by_status()
    logger.info(f"Images: {len(images)}, Open: {open_count}, Closed: {closed_count}")
    
    # If all images are closed, remain silent
    if open_count == 0 and closed_count > 0:
        logger.info("All images are closed - remaining silent")
        return

    # Fix the image selection logic for Group A
    # Try up to 5 times to get an image for the correct Group B
    max_attempts = 5
    image = None
    
    # Check if there are any Group B specific images for this request
    target_group_b = None
    # If there are multiple Group B chats, try to determine if there's a specific one we should use
    if len(GROUP_B_IDS) > 1:
        # Check message content to see if it contains info about target Group B
        # This is a simplified approach - you might want to implement something more robust
        logger.info(f"Multiple Group B chats detected: {GROUP_B_IDS}")
    
    for attempt in range(max_attempts):
        # Get a random open image
        random_image = db.get_random_open_image()
        if not random_image:
            update.message.reply_text("No open images available.")
            return
        
        # Get metadata and check if this image is from a specific Group B
        metadata = random_image.get('metadata', {})
        logger.info(f"Checking image {random_image['image_id']} metadata: {metadata}")
        
        if isinstance(metadata, dict) and 'source_group_b_id' in metadata:
            try:
                source_group_b_id = int(metadata['source_group_b_id'])
                
                # For each attempt, be more lenient in our criteria
                if attempt == 0:
                    # First attempt: Try to match exact Group B if we have a target
                    if target_group_b and source_group_b_id == target_group_b:
                        image = random_image
                        logger.info(f"Found exact matching image {image['image_id']} for Group B {source_group_b_id}")
                        break
                elif attempt < 3:
                    # Later attempts: Accept any image from a valid Group B
                    if source_group_b_id in GROUP_B_IDS or source_group_b_id == GROUP_B_ID:
                        image = random_image
                        logger.info(f"Found image {image['image_id']} from valid Group B {source_group_b_id}")
                        break
                else:
                    # Last attempts: Accept any image with metadata
                    image = random_image
                    logger.info(f"Accepting any image with metadata: {image['image_id']}")
                    break
            except (ValueError, TypeError) as e:
                logger.error(f"Error processing metadata for image {random_image['image_id']}: {e}")
        
        # If this was the last attempt, use this image regardless
        if attempt == max_attempts - 1:
            image = random_image
            logger.info(f"Using last attempted image: {image['image_id']}")
    
    # If still no image found, use the last random one we got
    if not image:
        image = random_image
        logger.info(f"No suitable image found after {max_attempts} attempts, using random image: {image['image_id']}")
    
    logger.info(f"Selected image: {image['image_id']}")
    
    # Send the image
    try:
        sent_msg = update.message.reply_photo(
            photo=image['file_id'],
            caption=f"🌟 群: {image['number']} 🌟"
        )
        logger.info(f"Image sent successfully with message_id: {sent_msg.message_id}")
        
        # Forward the content to the appropriate Group B chat
        try:
            # Get metadata if available
            metadata = image.get('metadata', {})
            logger.info(f"Image metadata: {metadata}")
            
            # Get the proper Group B ID for this image - this is the critical part
            target_group_b_id = get_group_b_for_image(image['image_id'], metadata)
            logger.info(f"Target Group B ID for forwarding: {target_group_b_id}")
            
            # Make EXTRA sure this is a valid Group B ID
            valid_group_b = False
            try:
                target_group_b_id_int = int(target_group_b_id)
                if target_group_b_id_int in [int(gid) for gid in GROUP_B_IDS] or target_group_b_id_int == int(GROUP_B_ID):
                    valid_group_b = True
                else:
                    logger.error(f"Target Group B ID {target_group_b_id_int} is not valid! Valid IDs: GROUP_B_IDS={GROUP_B_IDS}, GROUP_B_ID={GROUP_B_ID}")
                    # Fall back to main GROUP_B_ID
                    target_group_b_id = GROUP_B_ID
                    logger.info(f"Falling back to main GROUP_B_ID: {GROUP_B_ID}")
            except (ValueError, TypeError) as e:
                logger.error(f"Error validating target_group_b_id: {e}")
                # Fall back to main GROUP_B_ID
                target_group_b_id = GROUP_B_ID
                logger.info(f"Falling back to main GROUP_B_ID due to error: {GROUP_B_ID}")
            
            # Now we have a consistent target_group_b_id
            forwarded = context.bot.send_message(
                chat_id=target_group_b_id,
                text=f"💰 金额：{amount}\n🔢 群：{image['number']}\n\n❌ 如果会员10分钟没进群请回复0"
            )
            
            # Store mapping between original and forwarded message
            forwarded_msgs[image['image_id']] = {
                'group_a_msg_id': sent_msg.message_id,
                'group_a_chat_id': chat_id,  # Use the actual Group A chat ID that received this message
                'group_b_msg_id': forwarded.message_id,
                'group_b_chat_id': target_group_b_id,
                'image_id': image['image_id'],
                'amount': amount,  # Store the original amount
                'number': str(image['number']),  # Store the image number as string
                'original_user_id': update.message.from_user.id,  # Store original user for more robust tracking
                'original_message_id': update.message.message_id  # Store the original message ID to reply to
            }
            
            logger.info(f"Stored message mapping: {forwarded_msgs[image['image_id']]}")
            
            # Save persistent data
            save_persistent_data()
            
            # Set image status to closed
            db.set_image_status(image['image_id'], "closed")
            logger.info(f"Image {image['image_id']} status set to closed")
        except Exception as e:
            logger.error(f"Error forwarding to Group B: {e}")
            update.message.reply_text(f"发送至Group B失败: {e}")
    except Exception as e:
        logger.error(f"Error sending image: {e}")
        update.message.reply_text(f"发送图片错误: {e}")

def handle_approval(update: Update, context: CallbackContext) -> None:
    """Handle approval messages (reply with '1')."""
    # Check if the message is "1"
    if update.message.text != "1":
        return
    
    # Check if replying to a message
    if not update.message.reply_to_message:
        return
    
    # Check if replying to a bot message
    if update.message.reply_to_message.from_user.id != context.bot.id:
        return
    
    logger.info("Approval message detected")
    
    # Get the pending request
    request_msg_id = update.message.reply_to_message.message_id
    
    if request_msg_id in pending_requests:
        # Get request info
        request = pending_requests[request_msg_id]
        amount = request['amount']
        
        logger.info(f"Found pending request: {request}")
        
        # Get a random open image
        image = db.get_random_open_image()
        if not image:
            update.message.reply_text("No open images available.")
            return
        
        logger.info(f"Selected image: {image['image_id']}")
        
        # Send the image
        try:
            # Get the image and its metadata
            image = db.get_image_by_id(image['image_id'])
            metadata = image.get('metadata', {}) if image else {}
            
            # Get the proper Group B ID for this image
            target_group_b_id = get_group_b_for_image(image['image_id'], metadata)
            
            # First send the image to Group A
            sent_msg = update.message.reply_photo(
                photo=image['file_id'],
                caption=f"🌟 群: {image['number']} 🌟"
            )
            logger.info(f"Image sent to Group A with message_id: {sent_msg.message_id}")
            
            # Then forward to Group B
            forwarded = context.bot.send_message(
                chat_id=target_group_b_id,
                text=f"💰 金额：{amount}\n🔢 群：{image['number']}\n\n❌ 如果会员10分钟没进群请回复0"
            )
            logger.info(f"Message forwarded to Group B with message_id: {forwarded.message_id}")
            
            # Store mapping between original and forwarded message
            forwarded_msgs[image['image_id']] = {
                'group_a_msg_id': sent_msg.message_id,
                'group_a_chat_id': update.effective_chat.id,
                'group_b_msg_id': forwarded.message_id,
                'group_b_chat_id': target_group_b_id,
                'image_id': image['image_id'],
                'amount': amount,  # Store the original amount
                'number': str(image['number']),  # Store the image number as string
                'original_user_id': request['user_id'],  # Store original user for more robust tracking
                'original_message_id': request['original_message_id']  # Store the original message ID to reply to
            }
            
            logger.info(f"Stored message mapping: {forwarded_msgs[image['image_id']]}")
            
            # Save persistent data
            save_persistent_data()
            
            # Set image status to closed
            db.set_image_status(image['image_id'], "closed")
            logger.info(f"Image {image['image_id']} status set to closed")
            
            # Remove the pending request
            del pending_requests[request_msg_id]
        except Exception as e:
            logger.error(f"Error forwarding to Group B: {e}")
            update.message.reply_text(f"发送至Group B失败: {e}")
    else:
        logger.info(f"No pending request found for message ID: {request_msg_id}")

def handle_all_group_b_messages(update: Update, context: CallbackContext) -> None:
    """Single handler for ALL messages in Group B"""
    global FORWARDING_ENABLED
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    text = update.message.text.strip()
    user = update.effective_user.username or update.effective_user.first_name
    user_id = update.effective_user.id
    
    logger.info(f"Group B message: '{text}' from {user} (msg_id: {message_id})")
    
    # Skip empty messages
    if not text:
        return
    
    # Special case for "+0" or "0" responses - handle image status but don't send confirmation
    if (text == "+0" or text == "0") and update.message.reply_to_message:
        reply_msg_id = update.message.reply_to_message.message_id
        logger.info(f"Received {text} reply to message {reply_msg_id}")
        
        # Find if any known message matches this reply ID
        for img_id, data in forwarded_msgs.items():
            if data.get('group_b_msg_id') == reply_msg_id:
                logger.info(f"Found matching image {img_id} for {text} reply")
                
                # Save the Group B response
                group_b_responses[img_id] = "+0"
                logger.info(f"Stored Group B response: +0")
                
                # Save responses
                save_persistent_data()
                
                # Mark the image as open
                db.set_image_status(img_id, "open")
                logger.info(f"Set image {img_id} status to open")
                
                # Send response to Group A only if forwarding is enabled
                if FORWARDING_ENABLED:
                    if 'group_a_chat_id' in data and 'group_a_msg_id' in data:
                        try:
                            # Get the original message ID if available
                            original_message_id = data.get('original_message_id')
                            reply_to_message_id = original_message_id if original_message_id else data['group_a_msg_id']
                            
                            # Send response back to Group A
                            safe_send_message(
                                context=context,
                                chat_id=data['group_a_chat_id'],
                                text="会员没进群呢哥哥~ 😢",
                                reply_to_message_id=reply_to_message_id
                            )
                            logger.info(f"Sent +0 response to Group A (translated to '会员没进群呢哥哥~ 😢')")
                        except Exception as e:
                            logger.error(f"Error sending +0 response to Group A: {e}")
                    else:
                        logger.info("Group A chat ID or message ID not found in data")
                else:
                    logger.info("Forwarding to Group A is currently disabled by admin - not sending +0 response")
                
                return
    
    # Extract all numbers from the message (with or without + prefix)
    raw_numbers = re.findall(r'\d+', text)
    plus_numbers = [m[1:] for m in re.findall(r'\+\d+', text)]
    
    # Log what we found
    if raw_numbers:
        logger.info(f"Found raw numbers: {raw_numbers}")
    if plus_numbers:
        logger.info(f"Found numbers with + prefix: {plus_numbers}")
    
    # Regular handling for other messages
    # CASE 1: Check if replying to a message
    if update.message.reply_to_message:
        reply_msg_id = update.message.reply_to_message.message_id
        logger.info(f"This is a reply to message {reply_msg_id}")
        
        # Find if any known message matches this reply ID
        for img_id, data in forwarded_msgs.items():
            if data.get('group_b_msg_id') == reply_msg_id:
                logger.info(f"Found matching image {img_id} for this reply")
                stored_amount = data.get('amount')
                stored_number = data.get('number')
                logger.info(f"Expected amount: {stored_amount}, group number: {stored_number}")
                
                # If there's a number in the reply with + prefix
                if plus_numbers:
                    number = plus_numbers[0]  # Use the first +number
                    logger.info(f"User provided number: +{number}")
                    
                    # Verify the number matches the expected amount
                    if number == stored_amount:
                        logger.info(f"Provided number matches the expected amount: {stored_amount}")
                        process_group_b_response(update, context, img_id, data, number, f"+{number}", "reply_valid_amount")
                        return
                    elif number == stored_number:
                        # Number matches group number but not amount - silently ignore
                        logger.info(f"Number {number} matches group number but NOT the expected amount {stored_amount}")
                        return
                    else:
                        # Number doesn't match either amount or group number - CUSTOM AMOUNT
                        logger.info(f"Number {number} is a custom amount, different from {stored_amount}")
                        # Check if user is a group admin to allow custom amounts
                        if is_group_admin(user_id, chat_id) or is_global_admin(user_id):
                            # Handle custom amount that needs approval
                            handle_custom_amount(update, context, img_id, data, number)
                            return
                        else:
                            logger.info(f"User {user_id} is not an admin, silently ignoring custom amount")
                            return
                
                # If there's a raw number (without +)
                elif raw_numbers:
                    number = raw_numbers[0]  # Use the first raw number
                    logger.info(f"User provided raw number: {number}")
                    
                    # Verify the number matches the expected amount
                    if number == stored_amount:
                        logger.info(f"Provided number matches the expected amount: {stored_amount}")
                        process_group_b_response(update, context, img_id, data, number, f"+{number}", "reply_valid_amount_raw")
                        return
                    elif number == stored_number:
                        # Number matches group number but not amount - silently ignore
                        logger.info(f"Number {number} matches group number but NOT the expected amount {stored_amount}")
                        return
                    else:
                        # Number doesn't match either amount or group number - CUSTOM AMOUNT
                        logger.info(f"Number {number} is a custom amount, different from {stored_amount}")
                        # Check if user is a group admin to allow custom amounts
                        if is_group_admin(user_id, chat_id) or is_global_admin(user_id):
                            # Handle custom amount that needs approval
                            handle_custom_amount(update, context, img_id, data, number)
                            return
                        else:
                            logger.info(f"User {user_id} is not an admin, silently ignoring custom amount")
                            return
                
                # No numbers in reply - silently ignore
                else:
                    logger.info("Reply without any numbers detected")
                    return
        
        # If replying to a message that's not from our bot
        logger.info("Reply to a message that's not recognized as one of our bot's messages")
        return
    
    # At this point, the message is not a reply - only proceed for Group B admins and specific commands
    if "重置群码" in text or "设置群" in text or "设置群聊" in text or "设置操作人" in text or "解散群聊" in text:
        # These are handled by other message handlers, so let them through
        logger.info(f"Passing command message to other handlers: {text}")
        return
    
    # For standalone "+number" messages - we now silently ignore them
    if plus_numbers or (raw_numbers and len(text) <= 10):  # Simple number messages
        logger.info(f"Received standalone number message: {text}")
        # Silently ignore standalone number messages
        logger.info("Silently ignoring standalone number message")
        return
    
    # For any other messages, just log and take no action
    logger.info("No action taken for this message")

def process_group_b_response(update, context, img_id, msg_data, number, original_text, match_type):
    """Process a response from Group B and update status."""
    global FORWARDING_ENABLED
    responder = update.effective_user.username or update.effective_user.first_name
    
    # Simplified response format - just the +number or custom message for +0
    if number == "0" or original_text == "+0" or original_text == "0":
        response_text = "会员没进群呢哥哥~ 😢"
    else:
        if "+" in original_text:
            response_text = original_text  # Keep the original format if it already has +
        else:
            response_text = f"+{number}"  # Add + if missing
    
    logger.info(f"Processing Group B response for image {img_id} (match type: {match_type})")
    
    # Save the Group B response for this image
    group_b_responses[img_id] = response_text
    logger.info(f"Stored Group B response: {response_text}")
    
    # Save responses
    save_persistent_data()
    
    # Set status to open
    db.set_image_status(img_id, "open")
    logger.info(f"Set image {img_id} status to open")
    
    # Send the response to Group A chat
    if 'group_a_chat_id' in msg_data and 'group_a_msg_id' in msg_data:
        if FORWARDING_ENABLED:
            logger.info(f"Sending response to Group A: {msg_data['group_a_chat_id']}")
            try:
                # Get the original message ID if available
                original_message_id = msg_data.get('original_message_id')
                reply_to_message_id = original_message_id if original_message_id else msg_data['group_a_msg_id']
                
                # Send response back to Group A
                safe_send_message(
                    context=context,
                    chat_id=msg_data['group_a_chat_id'],
                    text=response_text,
                    reply_to_message_id=reply_to_message_id
                )
                logger.info(f"Successfully sent response to Group A {msg_data['group_a_chat_id']}: {response_text}")
            except Exception as e:
                logger.error(f"Error sending response to Group A: {e}")
                # No error messages to user
                logger.error("Could not notify user about Group A send failure")
        else:
            logger.info("Forwarding to Group A is currently disabled by admin")
            # No notification message when forwarding is disabled
    
    # No confirmation message to Group B
    logger.info(f"No confirmation sent to Group B for: {response_text}")

# Add handler for replies to bot messages in Group A
def handle_group_a_reply(update: Update, context: CallbackContext) -> None:
    """Handle replies to bot messages in Group A silently (no auto-replies)."""
    # Completely silent handler - no processing, no responses
    logger.info(f"Reply received in Group A - ignoring silently")
    return
    
    # All the processing below has been commented out to ensure complete silence
    """
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    reply_to_message_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None
    
    logger.info(f"Reply received in chat {chat_id} to message {reply_to_message_id}")
    
    # Check if replying to a message
    if not update.message.reply_to_message:
        logger.info("Not a reply to any message")
        return
    
    # Check if replying to a photo message (our bot images have photos)
    if not update.message.reply_to_message.photo:
        logger.info("Not replying to a photo message")
        return
    
    logger.info("Reply to photo message detected in Group A")
    logger.info(f"Current forwarded_msgs: {forwarded_msgs}")
    
    # Find the image ID for this message - just log information, don't reply
    found = False
    for img_id, msg_data in forwarded_msgs.items():
        group_a_msg_id = msg_data.get('group_a_msg_id')
        logger.info(f"Checking image {img_id} with group_a_msg_id: {group_a_msg_id}")
        
        # Check if the message IDs match
        if group_a_msg_id and str(group_a_msg_id) == str(reply_to_message_id):
            logger.info(f"Found matching image: {img_id}")
            found = True
            
            # Check if there's a response from Group B - just log it
            if img_id in group_b_responses:
                response = group_b_responses[img_id]
                logger.info(f"Group B response for image {img_id}: {response}")
            else:
                logger.info(f"No Group B response found for image {img_id}")
            
            break
    
    if not found:
        logger.info(f"No matching image found for reply to message {reply_to_message_id}")
        # No response if no match
    """

def button_callback(update: Update, context: CallbackContext) -> None:
    """Handle button callbacks."""
    global FORWARDING_ENABLED
    query = update.callback_query
    query.answer()
    
    # Parse callback data
    data = query.data
    if data.startswith('plus_'):
        image_id = data[5:]  # Remove 'plus_' prefix
        
        # Find the message data
        msg_data = None
        for img_id, data in forwarded_msgs.items():
            if img_id == image_id:
                msg_data = data
                break
        
        if msg_data:
            original_amount = msg_data.get('amount', '0')
            
            # Set up inline keyboard for amount verification
            keyboard = [
                [
                    InlineKeyboardButton(f"+{original_amount}", callback_data=f"verify_{image_id}_{original_amount}"),
                    InlineKeyboardButton("+0", callback_data=f"verify_{image_id}_0")
                ]
            ]
            
            try:
                query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                query.message.reply_text(f"请确认金额: +{original_amount} 或 +0（如果会员未进群）")
            except (NetworkError, TimedOut) as e:
                logger.error(f"Network error in button callback: {e}")
    
    elif data.startswith('verify_'):
        # Format: verify_image_id_amount
        parts = data.split('_')
        if len(parts) >= 3:
            image_id = parts[1]
            amount = parts[2]
            
            # Find the message data
            msg_data = None
            for img_id, data in forwarded_msgs.items():
                if img_id == image_id:
                    msg_data = data
                    break
            
            # Simplified response format - just +amount or custom message for +0
            response_text = "会员没进群呢哥哥~ 😢" if amount == "0" else f"+{amount}"
            
            # Store the response for Group A
            group_b_responses[image_id] = response_text
            logger.info(f"Stored Group B button response for image {image_id}: {response_text}")
            
            # Save updated responses
            save_persistent_data()
            
            try:
                # Set status to open
                if db.set_image_status(image_id, "open"):
                    query.edit_message_reply_markup(None)
                    
                # Only send response to Group A if forwarding is enabled
                if FORWARDING_ENABLED:
                    if msg_data and 'group_a_chat_id' in msg_data and 'group_a_msg_id' in msg_data:
                        try:
                            # Get the original message ID if available
                            original_message_id = msg_data.get('original_message_id')
                            reply_to_message_id = original_message_id if original_message_id else msg_data['group_a_msg_id']
                            
                            # Send response back to Group A using safe send method
                            safe_send_message(
                                context=context,
                                chat_id=msg_data['group_a_chat_id'],
                                text=response_text,
                                reply_to_message_id=reply_to_message_id
                            )
                            logger.info(f"Directly sent Group B button response to Group A: {response_text}")
                        except Exception as e:
                            logger.error(f"Error sending button response to Group A: {e}")
                            query.message.reply_text(f"回复已保存，但发送到需方群失败: {e}")
                else:
                    logger.info("Forwarding to Group A is currently disabled by admin - not sending button response")
                    # Remove the notification message
                    # query.message.reply_text("回复已保存，但转发到需方群功能当前已关闭。")
            except (NetworkError, TimedOut) as e:
                logger.error(f"Network error in verify callback: {e}")

def debug_command(update: Update, context: CallbackContext) -> None:
    """Debug command to display current state."""
    # Only allow in private chats from admin
    if update.effective_chat.type != "private" or not is_global_admin(update.effective_user.id):
        update.message.reply_text("Only global admins can use this command in private chat.")
        return
    
    debug_info = [
        f"🔹 Group A IDs: {GROUP_A_IDS}",
        f"🔸 Group B IDs: {GROUP_B_IDS}",
        f"👥 Group Admins: {GROUP_ADMINS}",
        f"📨 Forwarded Messages: {len(forwarded_msgs)}",
        f"📝 Group B Responses: {len(group_b_responses)}",
        f"🖼️ Images: {len(db.get_all_images())}",
        f"⚙️ Forwarding Enabled: {FORWARDING_ENABLED}"
    ]
    
    update.message.reply_text("\n".join(debug_info))

def register_admin_command(update: Update, context: CallbackContext) -> None:
    """Register a user as group admin by user ID."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Only allow global admins
    if not is_global_admin(user_id):
        update.message.reply_text("只有全局管理员可以使用此命令。")
        return
    
    # Check if we have arguments
    if not context.args or len(context.args) != 1:
        update.message.reply_text("用法: /admin <user_id> - 将用户设置为群操作人")
        return
    
    # Get the target user ID
    try:
        target_user_id = int(context.args[0])
        
        # Add the user as group admin
        add_group_admin(target_user_id, chat_id)
        
        update.message.reply_text(f"👤 用户 {target_user_id} A已设置为此群的操作人。")
        logger.info(f"User {target_user_id} manually added as group admin in chat {chat_id} by admin {user_id}")
    except ValueError:
        update.message.reply_text("用户 ID 必须是数字。")

def get_id_command(update: Update, context: CallbackContext) -> None:
    """Get user and chat IDs."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    message = f"👤 您的用户 ID: {user_id}\n🌐 群聊 ID: {chat_id}\n📱 群聊类型: {chat_type}"
    
    # If replying to someone, get their ID too
    if update.message.reply_to_message:
        replied_user_id = update.message.reply_to_message.from_user.id
        replied_user_name = update.message.reply_to_message.from_user.first_name
        message += f"\n\n↩️ 回复的用户信息:\n👤 用户 ID: {replied_user_id}\n📝 用户名: {replied_user_name}"
    
    update.message.reply_text(message)

def debug_reset_command(update: Update, context: CallbackContext) -> None:
    """Reset the forwarded_msgs and group_b_responses."""
    # Only allow in private chats from admin
    if update.effective_chat.type != "private" or update.effective_user.id not in GLOBAL_ADMINS:
        update.message.reply_text("Only admins can use this command in private chat.")
        return
    
    global forwarded_msgs, group_b_responses
    
    # Backup current data
    if os.path.exists(FORWARDED_MSGS_FILE):
        os.rename(FORWARDED_MSGS_FILE, f"{FORWARDED_MSGS_FILE}.bak")
    
    if os.path.exists(GROUP_B_RESPONSES_FILE):
        os.rename(GROUP_B_RESPONSES_FILE, f"{GROUP_B_RESPONSES_FILE}.bak")
    
    # Reset dictionaries
    forwarded_msgs = {}
    group_b_responses = {}
    
    # Save empty data
    save_persistent_data()
    
    update.message.reply_text("🔄 Message mappings and responses have been reset.")

def handle_admin_reply(update: Update, context: CallbackContext) -> None:
    """Handle admin replies with the word '群'."""
    user_id = update.effective_user.id
    
    # Check if user is an admin
    if user_id not in GLOBAL_ADMINS:
        logger.info(f"User {user_id} is not an admin")
        return
    
    # Check if message contains the word '群'
    if '群' not in update.message.text:
        return
    
    # Check if this is a reply to another message
    if not update.message.reply_to_message:
        return
    
    logger.info(f"Admin reply detected from user {user_id} with text: {update.message.text}")
    
    # Get the original message and user
    original_message = update.message.reply_to_message
    original_user_id = original_message.from_user.id
    original_message_id = original_message.message_id
    
    logger.info(f"Original message from user {original_user_id}: {original_message.text}")
    
    # Check if we have any images
    images = db.get_all_images()
    if not images:
        logger.info("No images found in database")
        update.message.reply_text("No images available. Please ask admin to set images.")
        return
        
    # Count open and closed images
    open_count, closed_count = db.count_images_by_status()
    logger.info(f"Images: {len(images)}, Open: {open_count}, Closed: {closed_count}")
    
    # If all images are closed, remain silent
    if open_count == 0 and closed_count > 0:
        logger.info("All images are closed - remaining silent")
        return
    
    # Get a random open image
    image = db.get_random_open_image()
    if not image:
        update.message.reply_text("No open images available.")
        return
    
    logger.info(f"Selected image: {image['image_id']}")
    
    # Get amount from original message if it's numeric
    amount = ""
    if original_message.text and original_message.text.strip().isdigit():
        amount = original_message.text.strip()
    else:
        # Try to extract numbers from the message
        numbers = re.findall(r'\d+', original_message.text if original_message.text else "")
        if numbers:
            amount = numbers[0]
        else:
            amount = "0"  # Default amount if no number found
    
    logger.info(f"Extracted amount: {amount}")
    
    # Send the image as a reply to the original message
    try:
        sent_msg = original_message.reply_photo(
            photo=image['file_id'],
            caption=f"Number: {image['number']}"
        )
        logger.info(f"Image sent successfully to Group A with message_id: {sent_msg.message_id}")
        
        # Forward the content to Group B
        try:
            if GROUP_B_ID:
                logger.info(f"Forwarding to Group B: {GROUP_B_ID}")
                forwarded = context.bot.send_message(
                    chat_id=GROUP_B_ID,
                    text=f"💰 金额：{amount}\n🔢 群：{image['number']}\n\n❌ 如果会员10分钟没进群请回复0"
                )
                logger.info(f"Message forwarded to Group B with message_id: {forwarded.message_id}")
                
                # Store mapping between original and forwarded message
                forwarded_msgs[image['image_id']] = {
                    'group_a_msg_id': sent_msg.message_id,
                    'group_a_chat_id': update.effective_chat.id,
                    'group_b_msg_id': forwarded.message_id,
                    'group_b_chat_id': GROUP_B_ID,
                    'image_id': image['image_id'],
                    'amount': amount,  # Store the original amount
                    'number': str(image['number']),  # Store the image number as string
                    'original_user_id': original_user_id,  # Store original user for more robust tracking
                    'original_message_id': original_message_id  # Store the original message ID to reply to
                }
                
                logger.info(f"Stored message mapping: {forwarded_msgs[image['image_id']]}")
                
                # Save the updated mappings
                save_persistent_data()
                
                # Set image status to closed
                db.set_image_status(image['image_id'], "closed")
                logger.info(f"Image {image['image_id']} status set to closed")
        except Exception as e:
            logger.error(f"Error forwarding to Group B: {e}")
            update.message.reply_text(f"Error forwarding to Group B: {e}")
    except Exception as e:
        logger.error(f"Error sending image: {e}")
        update.message.reply_text(f"Error sending image: {e}")

def handle_general_group_b_message(update: Update, context: CallbackContext) -> None:
    """Fallback handler for any text message in Group B."""
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    text = update.message.text.strip()
    user = update.effective_user.username or update.effective_user.first_name
    
    logger.info(f"General handler received: '{text}' from {user} (msg_id: {message_id})")
    
    # Extract numbers from text
    numbers = re.findall(r'\d+', text)
    if not numbers:
        logger.info("No numbers found in message, ignoring")
        return
    
    logger.info(f"Extracted numbers: {numbers}")
    
    # Try with each extracted number
    for number in numbers:
        # 1. FIRST APPROACH: Try to find match by reply
        if update.message.reply_to_message:
            reply_msg_id = update.message.reply_to_message.message_id
            logger.info(f"Message is a reply to message_id: {reply_msg_id}")
            
            # Look for the image that corresponds to this reply
            for img_id, msg_data in forwarded_msgs.items():
                if msg_data.get('group_b_msg_id') == reply_msg_id:
                    logger.info(f"Found matching image by reply: {img_id}")
                    
                    # Create appropriate text with + if needed
                    response_text = f"+{number}" if "+" not in text else text
                    
                    # Process this message
                    process_group_b_response(update, context, img_id, msg_data, number, response_text, "general_reply")
                    return
        
        # 2. SECOND APPROACH: Try to find match by number
        for img_id, msg_data in forwarded_msgs.items():
            amount = msg_data.get('amount')
            group_num = msg_data.get('number')
            
            logger.info(f"Checking image {img_id}: amount={amount}, number={group_num}")
            
            if number == amount:
                logger.info(f"Found match by amount: {img_id}")
                
                # Create appropriate text with + if needed
                response_text = f"+{number}" if "+" not in text else text
                
                process_group_b_response(update, context, img_id, msg_data, number, response_text, "general_amount")
                return
            
            if number == group_num:
                logger.info(f"Found match by group number: {img_id}")
                
                # Create appropriate text with + if needed
                response_text = f"+{number}" if "+" not in text else text
                
                process_group_b_response(update, context, img_id, msg_data, number, response_text, "general_group_number")
                return
    
    # 3. FALLBACK: Just try the most recent message if the message has only one number
    if len(numbers) == 1 and forwarded_msgs:
        number = numbers[0]
        
        # Sort by recency (assuming newer messages have higher IDs)
        recent_msgs = sorted(forwarded_msgs.items(), 
                             key=lambda x: x[1].get('group_b_msg_id', 0), 
                             reverse=True)
        
        if recent_msgs:
            img_id, msg_data = recent_msgs[0]
            logger.info(f"No match found, using most recent message: {img_id}")
            
            # Create appropriate text with + if needed
            response_text = f"+{number}" if "+" not in text else text
            
            process_group_b_response(update, context, img_id, msg_data, number, response_text, "general_recent")
            return
    
    # If nothing matches, just ignore the message
    logger.info("No matches found for this message")

# Update forward_message_to_group_b function to use consistent mapping
def forward_message_to_group_b(update: Update, context: CallbackContext, img_id, amount, number) -> None:
    """Forward a message from Group A to Group B."""
    chat_id = update.effective_chat.id
    message_id = update.message.message_id
    
    logger.info(f"Forwarding to Group B - img_id: {img_id}, amount: {amount}, number: {number}")
    
    # Check if it's in the format we're expecting
    if not all([img_id, amount, number]):
        logger.error("Missing required parameters for forwarding")
        return
    
    try:
        # Get image from database
        image = db.get_image_by_id(img_id)
        if not image:
            logger.error(f"No image found for ID {img_id}")
            return
        
        # Get the metadata
        metadata = image.get('metadata', {})
        
        # Get consistent Group B for this image
        target_group_b_id = get_group_b_for_image(img_id, metadata)
        
        # Construct caption
        message_text = f"💰 金额: {amount} 🔢 群: {number}\n\n❌ 如果会员10分钟没进群请回复0"
        
        # Send text message instead of photo
        forwarded = context.bot.send_message(
            chat_id=target_group_b_id,
            text=message_text
        )
        
        logger.info(f"Forwarded message for image {img_id} to Group B {target_group_b_id}")
        
        # Store the mapping
        forwarded_msgs[img_id] = {
            'group_a_chat_id': chat_id,
            'group_a_msg_id': message_id,
            'group_b_chat_id': target_group_b_id,
            'group_b_msg_id': forwarded.message_id,
            'image_id': img_id,
            'amount': amount,
            'number': number,
            'original_user_id': update.effective_user.id,
            'original_message_id': message_id
        }
        
        # Save the mapping
        save_persistent_data()
        
        # Mark the image as closed
        db.set_image_status(img_id, "closed")
        logger.info(f"Image {img_id} status set to closed")
        
    except Exception as e:
        logger.error(f"Error forwarding to Group B: {e}")
        update.message.reply_text(f"Error forwarding to Group B: {e}")

def handle_set_group_a(update: Update, context: CallbackContext) -> None:
    """Handle setting a group as Group A."""
    global dispatcher
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to set group as Group A but is not a global admin")
        update.message.reply_text("只有全局管理员可以设置群聊类型。")
        return
    
    # Add this chat to Group A - ensure we're storing as integer
    GROUP_A_IDS.add(int(chat_id))
    save_config_data()
    
    # Reload handlers to pick up the new group
    if dispatcher:
        register_handlers(dispatcher)
    
    logger.info(f"Group {chat_id} set as Group A by user {user_id}")
    # Notification removed

def handle_set_group_b(update: Update, context: CallbackContext) -> None:
    """Handle setting a group as Group B."""
    global dispatcher
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to set group as Group B but is not a global admin")
        update.message.reply_text("只有全局管理员可以设置群聊类型。")
        return
    
    # Add this chat to Group B - ensure we're storing as integer
    GROUP_B_IDS.add(int(chat_id))
    save_config_data()
    
    # Reload handlers to pick up the new group
    if dispatcher:
        register_handlers(dispatcher)
    
    logger.info(f"Group {chat_id} set as Group B by user {user_id}")
    # Notification removed

def handle_promote_group_admin(update: Update, context: CallbackContext) -> None:
    """Handle promoting a user to group admin."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to promote a group admin but is not a global admin")
        return
    
    # Check if replying to a user
    if not update.message.reply_to_message:
        update.message.reply_text("请回复要设置为操作人的用户消息。")
        return
    
    # Get the user to promote
    target_user_id = update.message.reply_to_message.from_user.id
    target_user_name = update.message.reply_to_message.from_user.first_name
    
    # Add the user as a group admin
    add_group_admin(target_user_id, chat_id)
    
    update.message.reply_text(f"👑 已将用户 {target_user_name} 设置为群操作人。")
    logger.info(f"User {target_user_id} promoted to group admin in chat {chat_id} by user {user_id}")

def handle_set_group_image(update: Update, context: CallbackContext) -> None:
    """Handle setting an image for a specific group number."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    logger.info(f"Image setting attempt in chat {chat_id} by user {user_id}")
    
    # Debug registered Group B chats
    logger.info(f"Current Group B chats: {GROUP_B_IDS}")
    
    # Check if this is a Group B chat
    if chat_id not in GROUP_B_IDS:
        logger.warning(f"User tried to set image in non-Group B chat: {chat_id}")
        update.message.reply_text("此群聊未设置为需方群 (Group B)，请联系全局管理员设置。")
        return
    
    # Debug admin status
    is_admin = is_group_admin(user_id, chat_id)
    is_global = is_global_admin(user_id)
    logger.info(f"User {user_id} is group admin: {is_admin}, is global admin: {is_global}")
    
    # Debug group admins for this chat
    if chat_id in GROUP_ADMINS:
        logger.info(f"Group admins for chat {chat_id}: {GROUP_ADMINS[chat_id]}")
    else:
        logger.info(f"No group admins registered for chat {chat_id}")
    
    # For testing, allow all users to set images temporarily
    allow_all_users = False  # Set to True for debugging
    
    # Check if user is a group admin or global admin
    if not allow_all_users and not is_group_admin(user_id, chat_id) and not is_global_admin(user_id):
        logger.warning(f"User {user_id} tried to set image but is not an admin")
        update.message.reply_text("只有群操作人可以设置图片。请联系管理员。")
        return
    
    # Check if message has a photo
    if not update.message.photo:
        logger.warning(f"No photo in message")
        update.message.reply_text("请发送一张图片并备注'设置群 {number}'。")
        return
    
    # Debug caption
    caption = update.message.caption or ""
    logger.info(f"Caption: '{caption}'")
    
    # Extract group number from message text
    match = re.search(r'设置群\s*(\d+)', caption)
    if not match:
        logger.warning(f"Caption doesn't match pattern: '{caption}'")
        update.message.reply_text("请使用正确的格式：设置群 {number}")
        return
    
    group_number = match.group(1)
    logger.info(f"Setting image for group {group_number}")
    
    # Get the file_id of the image
    file_id = update.message.photo[-1].file_id
    image_id = f"img_{int(time.time())}"  # Use timestamp for unique ID
    
    # Store which Group B chat this image came from
    source_group_b_id = int(chat_id)  # Explicitly convert to int to ensure consistent type
    logger.info(f"Setting image source Group B ID: {source_group_b_id}")
    
    # Find a target Group A for this Group B
    target_group_a_id = None
    
    # First, check if we have a specific Group A that corresponds to this Group B
    # For simplicity, we'll use the first Group A in the list
    if GROUP_A_IDS:
        target_group_a_id = next(iter(GROUP_A_IDS))
    else:
        target_group_a_id = GROUP_A_ID
    
    logger.info(f"Setting image target Group A ID: {target_group_a_id}")
    
    # Debug image data
    logger.info(f"Image data - ID: {image_id}, file_id: {file_id}, group: {group_number}")
    logger.info(f"Source Group B: {source_group_b_id}, Target Group A: {target_group_a_id}")
    
    # Save the image with additional metadata
    try:
        # Store the metadata in a separate JSON field - make sure source_group_b_id is explicitly an int
        metadata_dict = {
            'source_group_b_id': source_group_b_id,
            'target_group_a_id': target_group_a_id
        }
        
        # Convert to JSON string
        metadata = json.dumps(metadata_dict)
        
        logger.info(f"Saving image with metadata: {metadata}")
        
        success = db.add_image(image_id, int(group_number), file_id, metadata=metadata)
        if success:
            # Double check that the image was set correctly
            saved_image = db.get_image_by_id(image_id)
            if saved_image and 'metadata' in saved_image:
                logger.info(f"Verified image metadata: {saved_image['metadata']}")
            
            logger.info(f"Successfully added image {image_id} for group {group_number}")
            update.message.reply_text(f"✅ 已设置群聊为{group_number}群")
        else:
            logger.error(f"Failed to add image {image_id} for group {group_number}")
            update.message.reply_text("设置图片失败，该图片可能已存在。请重试。")
    except Exception as e:
        logger.error(f"Exception when adding image: {e}")
        update.message.reply_text(f"设置图片时出错: {str(e)}")

def handle_custom_amount(update: Update, context: CallbackContext, img_id, msg_data, number) -> None:
    """Handle custom amount that needs approval."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    custom_message = update.message.text
    message_id = update.message.message_id
    reply_to_message_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None
    
    logger.info(f"Custom amount detected: {number}")
    
    # Store the custom amount approval with more detailed info
    pending_custom_amounts[message_id] = {
        'img_id': img_id,
        'amount': number,
        'responder': user_id,
        'responder_name': user_name,
        'original_msg_id': message_id,  # The ID of the message with the custom amount
        'reply_to_msg_id': reply_to_message_id,  # The ID of the message being replied to
        'message_text': custom_message,
        'timestamp': datetime.now().isoformat()
    }
    
    # Save updated responses
    save_persistent_data()
    
    # Create mention tags for global admins
    admin_mentions = ""
    for admin_id in GLOBAL_ADMINS:
        try:
            # Get admin chat member info to get username or first name
            admin_user = context.bot.get_chat_member(chat_id, admin_id).user
            admin_name = admin_user.username or admin_user.first_name
            admin_mentions += f"@{admin_name} "
        except Exception as e:
            logger.error(f"Error getting admin info for ID {admin_id}: {e}")
    
    # Send notification in Group B about pending approval, including admin mentions
    notification_text = f"👤 用户 {user_name} 提交的自定义金额 +{number} 需要全局管理员确认 {admin_mentions}"
    update.message.reply_text(notification_text)
    
    # No longer sending confirmation to user
    
    # Notify all global admins about the pending approval
    for admin_id in GLOBAL_ADMINS:
        try:
            # Try to send private message to global admin
            original_amount = msg_data.get('amount')
            group_number = msg_data.get('number')
            
            notification_text = (
                f"🔔 需要审批:\n"
                f"👤 用户 {user_name} (ID: {user_id}) 在群 B 提交了自定义金额:\n"
                f"💰 原始金额: {original_amount}\n"
                f"💲 自定义金额: {number}\n"
                f"🔢 群号: {group_number}\n\n"
                f"✅ 审批方式:\n"
                f"1️⃣ 直接回复此消息并输入\"同意\"或\"确认\"\n"
                f"2️⃣ 或在群 B 找到用户发送的自定义金额消息（例如: +{number}）并回复\"同意\"或\"确认\""
            )
            
            # Attempt to send notification to admin
            context.bot.send_message(
                chat_id=admin_id,
                text=notification_text
            )
            logger.info(f"Sent approval notification to admin {admin_id}")
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

# Add this new function to handle global admin approvals
def handle_custom_amount_approval(update: Update, context: CallbackContext) -> None:
    """Handle global admin approval of custom amount."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to approve custom amount but is not a global admin")
        return
    
    # Check if this is a reply and contains "同意" or "确认"
    if not update.message.reply_to_message or not any(word in update.message.text for word in ["同意", "确认"]):
        return
    
    logger.info(f"Global admin {user_id} approval attempt detected")
    
    # If we're in a private chat, this is likely a reply to the notification
    # So we need to find the latest pending custom amount
    if update.effective_chat.type == "private":
        logger.info("Approval in private chat detected, finding most recent pending custom amount")
        
        if not pending_custom_amounts:
            logger.info("No pending custom amounts found")
            update.message.reply_text("没有待审批的自定义金额。")
            return
        
        # Find the most recent pending custom amount
        most_recent_msg_id = max(pending_custom_amounts.keys())
        approval_data = pending_custom_amounts[most_recent_msg_id]
        
        logger.info(f"Found most recent pending custom amount: {approval_data}")
        
        # Process the approval
        process_custom_amount_approval(update, context, most_recent_msg_id, approval_data)
        return
    
    # If we're in a group chat, check if this is a reply to a custom amount message
    reply_msg_id = update.message.reply_to_message.message_id
    logger.info(f"Checking if message {reply_msg_id} has a pending approval")
    
    # Debug all pending custom amounts to check what's stored
    logger.info(f"All pending custom amounts: {pending_custom_amounts}")
    
    # First, check if the message being replied to is directly in pending_custom_amounts
    if reply_msg_id in pending_custom_amounts:
        logger.info(f"Found direct match for message {reply_msg_id}")
        approval_data = pending_custom_amounts[reply_msg_id]
        process_custom_amount_approval(update, context, reply_msg_id, approval_data)
        return
    
    # If not, search through all pending approvals
    for msg_id, data in pending_custom_amounts.items():
        logger.info(f"Checking pending approval {msg_id} with data {data}")
        
        # Check if any of the stored message IDs match
        if (data.get('original_msg_id') == reply_msg_id or 
            str(data.get('original_msg_id')) == str(reply_msg_id) or
            data.get('reply_to_msg_id') == reply_msg_id or
            str(data.get('reply_to_msg_id')) == str(reply_msg_id)):
            
            logger.info(f"Found matching pending approval through message ID comparison: {msg_id}")
            process_custom_amount_approval(update, context, msg_id, data)
            return
    
    # If we still can't find it, try checking the message content
    reply_message_text = update.message.reply_to_message.text if update.message.reply_to_message.text else ""
    for msg_id, data in pending_custom_amounts.items():
        custom_amount = data.get('amount')
        if f"+{custom_amount}" in reply_message_text:
            logger.info(f"Found matching pending approval through message content: {msg_id}")
            process_custom_amount_approval(update, context, msg_id, data)
            return
    
    logger.info(f"No pending approval found for message ID: {reply_msg_id}")
    update.message.reply_text("⚠️ 没有找到此消息的待审批记录。请检查是否回复了正确的消息。")

def process_custom_amount_approval(update, context, msg_id, approval_data):
    """Process a custom amount approval."""
    global FORWARDING_ENABLED
    img_id = approval_data['img_id']
    custom_amount = approval_data['amount']
    approver_id = update.effective_user.id
    approver_name = update.effective_user.username or update.effective_user.first_name
    
    logger.info(f"Processing approval for image {img_id} with custom amount {custom_amount}")
    logger.info(f"Approval by {approver_name} (ID: {approver_id})")
    logger.info(f"Full approval data: {approval_data}")
    
    # Get the corresponding forwarded message data
    if img_id in forwarded_msgs:
        msg_data = forwarded_msgs[img_id]
        logger.info(f"Found forwarded message data: {msg_data}")
        
        # Process the custom amount like a regular response
        response_text = f"+{custom_amount}"
        
        # Save the response
        group_b_responses[img_id] = response_text
        logger.info(f"Stored custom amount response: {response_text}")
        
        # Save responses
        save_persistent_data()
        
        # Mark the image as open
        db.set_image_status(img_id, "open")
        logger.info(f"Set image {img_id} status to open after custom amount approval")
        
        # Send response to Group A only if forwarding is enabled
        if FORWARDING_ENABLED:
            if 'group_a_chat_id' in msg_data and 'group_a_msg_id' in msg_data:
                try:
                    # Get the original message ID if available
                    original_message_id = msg_data.get('original_message_id')
                    reply_to_message_id = original_message_id if original_message_id else msg_data['group_a_msg_id']
                    
                    logger.info(f"Sending response to Group A - chat_id: {msg_data['group_a_chat_id']}, reply_to: {reply_to_message_id}")
                    
                    # Send response back to Group A
                    sent_msg = safe_send_message(
                        context=context,
                        chat_id=msg_data['group_a_chat_id'],
                        text=response_text,
                        reply_to_message_id=reply_to_message_id
                    )
                    
                    if sent_msg:
                        logger.info(f"Successfully sent custom amount response to Group A: {response_text}")
                    else:
                        logger.warning("safe_send_message completed but did not return a message object")
                except Exception as e:
                    logger.error(f"Error sending custom amount response to Group A: {e}")
                    update.message.reply_text(f"金额已批准，但发送到需方群失败: {e}")
                    return
            else:
                logger.error(f"Missing group_a_chat_id or group_a_msg_id in msg_data: {msg_data}")
                update.message.reply_text("金额已批准，但找不到需方群的消息信息，无法发送回复。")
                return
        else:
            logger.info("Forwarding to Group A is currently disabled by admin - not sending custom amount")
            # Remove the notification message
            # update.message.reply_text("金额已批准，但转发到需方群功能当前已关闭。")
        
        # Send approval confirmation message to Group B
        if update.effective_chat.type == "private":
            # If approved in private chat, send notification to Group B
            if 'group_b_chat_id' in msg_data and msg_data['group_b_chat_id']:
                try:
                    context.bot.send_message(
                        chat_id=msg_data['group_b_chat_id'],
                        text=f"✅ 金额确认修改：+{custom_amount} (由管理员 {approver_name} 批准)",
                        reply_to_message_id=approval_data.get('reply_to_msg_id')
                    )
                    logger.info(f"Sent confirmation message in Group B about approved amount {custom_amount}")
                except Exception as e:
                    logger.error(f"Error sending confirmation to Group B: {e}")
        else:
            # If approved in group chat (Group B), send confirmation in the same chat
            update.message.reply_text(f"✅ 金额确认修改：+{custom_amount}")
            logger.info(f"Sent confirmation message in Group B about approved amount {custom_amount}")
        
        # Remove the admin confirmation message
        # No longer sending "自定义金额 X 已批准，并已发送到群A"
        
        # Delete the pending approval
        if msg_id in pending_custom_amounts:
            del pending_custom_amounts[msg_id]
            logger.info(f"Deleted pending approval with ID {msg_id}")
            save_persistent_data()
        else:
            logger.warning(f"Tried to delete non-existent pending approval with ID {msg_id}")
        
    else:
        logger.error(f"Image {img_id} not found in forwarded_msgs")
        update.message.reply_text("无法找到相关图片信息，批准失败。")

# Add this function to display global admins
def admin_list_command(update: Update, context: CallbackContext) -> None:
    """Display the list of global admins."""
    user_id = update.effective_user.id
    
    # Only allow global admins to see the list
    if not is_global_admin(user_id):
        update.message.reply_text("只有全局管理员可以使用此命令。")
        return
    
    # Format the list of global admins
    admin_list = []
    for admin_id in GLOBAL_ADMINS:
        try:
            # Try to get admin's username
            chat = context.bot.get_chat(admin_id)
            admin_name = chat.username or chat.first_name or "Unknown"
            admin_list.append(f"ID: {admin_id} - @{admin_name}")
        except Exception as e:
            # If can't get username, just show ID
            admin_list.append(f"ID: {admin_id}")
    
    # Send the formatted list
    message = "👑 全局管理员列表:\n" + "\n".join(admin_list)
    update.message.reply_text(message)

# Add this function to handle group image reset
def handle_group_b_reset_images(update: Update, context: CallbackContext) -> None:
    """Handle the command to reset all images in Group B."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Check if this is Group B
    if chat_id not in GROUP_B_IDS and chat_id != GROUP_B_ID:
        logger.info(f"Reset images command used in non-Group B chat: {chat_id}")
        return
    
    # Check if the message is exactly "重置群码"
    if message_text != "重置群码":
        return
    
    # Check if user is a group admin or global admin
    if not is_group_admin(user_id, chat_id) and not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to reset images but is not an admin")
        update.message.reply_text("只有群操作人或全局管理员可以重置群码。")
        return
    
    logger.info(f"Admin {user_id} is resetting images in Group B: {chat_id}")
    
    # Get current image count for this specific Group B for reporting
    all_images = db.get_all_images()
    logger.info(f"Total images in database before reset: {len(all_images)}")
    
    # Count images associated with this Group B
    group_b_images = []
    if all_images:
        for img in all_images:
            metadata = img.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
                    
            if isinstance(metadata, dict) and 'source_group_b_id' in metadata:
                try:
                    if int(metadata['source_group_b_id']) == int(chat_id):
                        group_b_images.append(img)
                except (ValueError, TypeError) as e:
                    logger.error(f"Error comparing Group B IDs: {e}")
    
    image_count = len(group_b_images)
    logger.info(f"Found {image_count} images associated with Group B {chat_id}")
    
    # Backup the existing images before deleting
    backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"images_backup_{backup_time}.json"
    
    try:
        with open(backup_file, 'w') as f:
            json.dump(group_b_images, f, indent=2)
        logger.info(f"Backed up {image_count} images for Group B {chat_id} to {backup_file}")
    except Exception as e:
        logger.error(f"Error backing up images: {e}")
    
    # Delete only images from this Group B
    try:
        # Use our new function to delete only images from this Group B
        success = db.clear_images_by_group_b(chat_id)
        
        # Also clear related message mappings for this Group B
        global forwarded_msgs, group_b_responses
        
        # Filter out messages related to this Group B
        if forwarded_msgs:
            # Create a new dict to avoid changing size during iteration
            new_forwarded_msgs = {}
            for msg_id, data in forwarded_msgs.items():
                # If the message was sent to this Group B, remove it
                if 'group_b_chat_id' in data and int(data['group_b_chat_id']) != int(chat_id):
                    new_forwarded_msgs[msg_id] = data
                else:
                    logger.info(f"Removing forwarded message mapping for {msg_id}")
            
            forwarded_msgs = new_forwarded_msgs
        
        # Same for group_b_responses
        if group_b_responses:
            new_group_b_responses = {}
            for msg_id, data in group_b_responses.items():
                if 'chat_id' in data and int(data['chat_id']) != int(chat_id):
                    new_group_b_responses[msg_id] = data
            group_b_responses = new_group_b_responses
        
        save_persistent_data()
        
        # Check if all images for this Group B were actually deleted
        remaining_images = db.get_all_images()
        remaining_for_group_b = []
        
        for img in remaining_images:
            metadata = img.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
                    
            if isinstance(metadata, dict) and 'source_group_b_id' in metadata:
                try:
                    if int(metadata['source_group_b_id']) == int(chat_id):
                        remaining_for_group_b.append(img)
                except (ValueError, TypeError) as e:
                    logger.error(f"Error comparing Group B IDs: {e}")
        
        if success:
            if not remaining_for_group_b:
                logger.info(f"Successfully cleared {image_count} images for Group B: {chat_id}")
                update.message.reply_text(f"🔄 已重置所有群码! 共清除了 {image_count} 个图片。")
            else:
                # Some images still exist for this Group B
                logger.warning(f"Reset didn't clear all images. {len(remaining_for_group_b)} images still remain for Group B {chat_id}")
                update.message.reply_text(f"⚠️ 群码重置部分完成。已清除 {image_count - len(remaining_for_group_b)} 个图片，但还有 {len(remaining_for_group_b)} 个图片未能清除。")
        else:
            logger.error(f"Failed to clear images for Group B: {chat_id}")
            update.message.reply_text("重置群码时出错，请查看日志。")
    except Exception as e:
        logger.error(f"Error clearing images: {e}")
        update.message.reply_text(f"重置群码时出错: {e}")

def set_image_group_b(update: Update, context: CallbackContext) -> None:
    """Set which Group B an image should be associated with."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Only allow global admins
    if not is_global_admin(user_id):
        update.message.reply_text("Only global admins can use this command.")
        return
    
    # Check if we have enough arguments: /setimagegroup <image_id> <group_b_id>
    if not context.args or len(context.args) < 2:
        update.message.reply_text("Usage: /setimagegroup <image_id> <group_b_id>")
        return
    
    image_id = context.args[0]
    group_b_id = int(context.args[1])
    
    # Get the image
    image = db.get_image_by_id(image_id)
    if not image:
        update.message.reply_text(f"Image with ID {image_id} not found.")
        return
    
    # Create metadata
    metadata = {
        'source_group_b_id': group_b_id,
        'target_group_a_id': GROUP_A_ID  # Default to main Group A
    }
    
    # If image already has metadata, update it
    if 'metadata' in image and isinstance(image['metadata'], dict):
        image['metadata'].update(metadata)
        metadata = image['metadata']
    
    # Update the image in database
    success = db.update_image_metadata(image_id, json.dumps(metadata))
    
    if success:
        update.message.reply_text(f"✅ Image {image_id} updated to use Group B: {group_b_id}")
    else:
        update.message.reply_text(f"❌ Failed to update image {image_id}")

# Add a debug_metadata command
def debug_metadata(update: Update, context: CallbackContext) -> None:
    """Debug command to check image metadata."""
    user_id = update.effective_user.id
    
    # Only allow global admins
    if not is_global_admin(user_id):
        update.message.reply_text("Only global admins can use this command.")
        return
    
    # Get all images
    images = db.get_all_images()
    if not images:
        update.message.reply_text("No images available.")
        return
    
    # Format the metadata for each image
    message_parts = ["📋 Image Metadata Debug:"]
    
    for img in images:
        image_id = img['image_id']
        status = img['status']
        number = img['number']
        
        metadata_str = "None"
        if 'metadata' in img:
            if isinstance(img['metadata'], dict):
                metadata_str = str(img['metadata'])
            else:
                try:
                    metadata_str = str(json.loads(img['metadata']) if img['metadata'] else {})
                except:
                    metadata_str = f"Error parsing: {img['metadata']}"
        
        # Check which Group B this image would go to
        target_group_b = get_group_b_for_image(image_id, img.get('metadata', {}))
        
        message_parts.append(f"🔢 Group: {number} | 🆔 ID: {image_id} | ⚡ Status: {status}")
        message_parts.append(f"📊 Metadata: {metadata_str}")
        message_parts.append(f"🔸 Target Group B: {target_group_b}")
        message_parts.append("")  # Empty line for spacing
    
    # Send the debug info
    message = "\n".join(message_parts)
    
    # If message is too long, split it
    if len(message) > 4000:
        # Send in chunks
        chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]
        for chunk in chunks:
            update.message.reply_text(chunk)
    else:
        update.message.reply_text(message)

# Add a global variable to store the dispatcher
dispatcher = None

# Define error handler at global scope
def error_handler(update, context):
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error: {context.error}")
    # If it's a network error, just log it
    if isinstance(context.error, (NetworkError, TimedOut, RetryAfter)):
        logger.error(f"Network error: {context.error}")

def register_handlers(dispatcher):
    """Register all message handlers. Called at startup and when groups change."""
    # Clear existing handlers first - use proper way to clear handlers
    for group in list(dispatcher.handlers.keys()):
        dispatcher.handlers[group].clear()
    
    # Add command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("setimage", set_image))
    dispatcher.add_handler(CommandHandler("images", list_images))
    dispatcher.add_handler(CommandHandler("debug", debug_command))
    dispatcher.add_handler(CommandHandler("debug_metadata", debug_metadata))
    dispatcher.add_handler(CommandHandler("dreset", debug_reset_command))
    dispatcher.add_handler(CommandHandler("admin", register_admin_command))
    dispatcher.add_handler(CommandHandler("id", get_id_command))
    dispatcher.add_handler(CommandHandler("adminlist", admin_list_command))
    dispatcher.add_handler(CommandHandler("setimagegroup", set_image_group_b))
    
    # Handler for admin image sending
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^发图'),
        handle_admin_send_image,
        run_async=True
    ))
    
    # Handler for setting groups
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^设置群聊A$'),
        handle_set_group_a,
        run_async=True
    ))
    
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^设置群聊B$'),
        handle_set_group_b,
        run_async=True
    ))
    
    # Handler for dissolving group settings
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^解散群聊$'),
        handle_dissolve_group,
        run_async=True
    ))
    
    # Handler for promoting group admins
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^设置操作人$') & Filters.reply,
        handle_promote_group_admin,
        run_async=True
    ))
    
    # Handler for setting images in Group B
    dispatcher.add_handler(MessageHandler(
        Filters.photo & Filters.caption_regex(r'设置群\s*\d+'),
        handle_set_group_image,
        run_async=True
    ))
    
    # 1. Handle button callbacks (highest priority)
    dispatcher.add_handler(CallbackQueryHandler(button_callback))
    
    # 2. Add handler for resetting all images in Group B - moved to higher priority
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^重置群码$') & (Filters.chat(GROUP_B_ID) | Filters.chat(list(GROUP_B_IDS))),
        handle_group_b_reset_images,
        run_async=True
    ))
    
    # 3. Add handler for resetting a specific image by number
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^重置群\d+$') & (Filters.chat(GROUP_B_ID) | Filters.chat(list(GROUP_B_IDS))),
        handle_reset_specific_image,
        run_async=True
    ))
    
    # 4. Add handler for custom amount approval
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.regex(r'^(同意|确认)$') & Filters.reply,
        handle_custom_amount_approval,
        run_async=True
    ))
    
    # 5. Group B message handling - single handler for everything
    # Updated to support multiple Group B chats
    dispatcher.add_handler(MessageHandler(
        Filters.text & (Filters.chat(GROUP_B_ID) | Filters.chat(list(GROUP_B_IDS))),
        handle_all_group_b_messages,
        run_async=True
    ))
    
    # 6. Group A message handling
    # First admin replies with '群'
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.reply & Filters.regex(r'^群$'),
        handle_admin_reply,
        run_async=True
    ))
    
    # Then replies to bot messages in Group A
    dispatcher.add_handler(MessageHandler(
        Filters.text & Filters.reply & (Filters.chat(GROUP_A_ID) | Filters.chat(list(GROUP_A_IDS))),
        handle_group_a_reply,
        run_async=True
    ))
    
    # Simple number messages in Group A (Updated to support both "{number} 群" and pure number formats)
    dispatcher.add_handler(MessageHandler(
        Filters.text & 
        ~Filters.regex(r'^\+') &  # Exclude messages starting with +
        ((Filters.regex(r'^\d+\s*群$') | Filters.regex(r'^\d+$')) &  # Match either number+群 or pure number 
         (Filters.chat(GROUP_A_ID) | Filters.chat(list(GROUP_A_IDS)))),
        handle_group_a_message,
        run_async=True
    ))
    
    # Add error handler
    dispatcher.add_error_handler(error_handler)
    
    logger.info(f"Handlers registered with Group A IDs: {GROUP_A_IDS}, Group B IDs: {GROUP_B_IDS}")
    
    # Handler for toggling forwarding status - works in any chat for global admins
    dispatcher.add_handler(MessageHandler(
        Filters.text & (Filters.regex(r'^开启转发$') | Filters.regex(r'^关闭转发$') | Filters.regex(r'^转发状态$')),
        handle_toggle_forwarding,
        run_async=True
    ))
    
    # Add commands for forwarding control in private chat
    dispatcher.add_handler(CommandHandler("forwarding_on", handle_toggle_forwarding, Filters.chat_type.private))
    dispatcher.add_handler(CommandHandler("forwarding_off", handle_toggle_forwarding, Filters.chat_type.private))
    dispatcher.add_handler(CommandHandler("forwarding_status", handle_toggle_forwarding, Filters.chat_type.private))

def main() -> None:
    """Start the bot."""
    global dispatcher
    
    if not TOKEN:
        logger.error("No token provided. Set TELEGRAM_BOT_TOKEN environment variable.")
        return
    
    # Load persistent data
    load_persistent_data()
    load_config_data()  # Make sure to load configuration data as well
    
    # Create the Updater and pass it your bot's token with more generous timeouts
    request_kwargs = {
        'read_timeout': 60,        # Increased from 30
        'connect_timeout': 60,     # Increased from 30
        'con_pool_size': 10,       # Default is 1, increasing for better parallelism
    }
    updater = Updater(TOKEN, request_kwargs=request_kwargs)
    
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    
    # Register all handlers
    register_handlers(dispatcher)
    
    # Start the Bot
    updater.start_polling()
    updater.idle()

def handle_dissolve_group(update: Update, context: CallbackContext) -> None:
    """Handle clearing settings for the current group only."""
    global dispatcher
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to dissolve group {chat_id} but is not a global admin")
        update.message.reply_text("只有全局管理员可以解散群聊设置。")
        return
    
    # Check if this chat is in either Group A or Group B
    in_group_a = int(chat_id) in GROUP_A_IDS
    in_group_b = int(chat_id) in GROUP_B_IDS
    
    if not (in_group_a or in_group_b):
        logger.info(f"Group {chat_id} is not configured as Group A or Group B")
        update.message.reply_text("此群聊未设置为任何群组类型。")
        return
    
    # Remove only this specific chat from the appropriate group
    if in_group_a:
        GROUP_A_IDS.discard(int(chat_id))
        group_type = "供方群 (Group A)"
    elif in_group_b:
        GROUP_B_IDS.discard(int(chat_id))
        group_type = "需方群 (Group B)"
    
    # Save the configuration
    save_config_data()
    
    # Reload handlers to reflect changes
    if dispatcher:
        register_handlers(dispatcher)
    
    logger.info(f"Group {chat_id} removed from {group_type} by user {user_id}")
    update.message.reply_text(f"✅ 此群聊已从{group_type}中移除。其他群聊不受影响。")

def handle_toggle_forwarding(update: Update, context: CallbackContext) -> None:
    """Toggle the forwarding status between Group B and Group A."""
    global FORWARDING_ENABLED
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to toggle forwarding but is not a global admin")
        update.message.reply_text("只有全局管理员可以切换转发状态。")
        return
    
    # Get command text
    text = update.message.text.strip().lower()
    
    # Determine whether to open or close forwarding
    if "开启转发" in text:
        FORWARDING_ENABLED = True
        status_message = "✅ 群转发功能已开启 - 消息将从群B转发到群A"
    elif "关闭转发" in text:
        FORWARDING_ENABLED = False
        status_message = "🚫 群转发功能已关闭 - 消息将不会从群B转发到群A"
    else:
        # Toggle current state if just "转发状态"
        FORWARDING_ENABLED = not FORWARDING_ENABLED
        status_message = "✅ 群转发功能已开启" if FORWARDING_ENABLED else "🚫 群转发功能已关闭"
    
    # Save configuration
    save_config_data()
    
    logger.info(f"Forwarding status set to {FORWARDING_ENABLED} by user {user_id} in {chat_type} chat")
    update.message.reply_text(status_message)

def handle_admin_send_image(update: Update, context: CallbackContext) -> None:
    """Allow global admins to manually send an image."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if user is a global admin
    if not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to use admin send image feature but is not a global admin")
        return
    
    logger.info(f"Global admin {user_id} is using send image feature")
    
    # Get message text (remove the command part)
    full_text = update.message.text.strip()
    
    # Check if there's a target number in the message
    number_match = re.search(r'群(\d+)', full_text)
    number = number_match.group(1) if number_match else None
    
    # Check if we have images in database
    images = db.get_all_images()
    if not images:
        logger.info("No images found in database")
        update.message.reply_text("没有可用的图片。")
        return
    
    # Get an image - if number specified, try to match it
    image = None
    if number:
        # Try to find image with matching number
        for img in images:
            if str(img.get('number')) == number:
                image = img
                logger.info(f"Found image with number {number}: {img['image_id']}")
                break
        
        # If no match found, inform admin
        if not image:
            logger.info(f"No image found with number {number}")
            update.message.reply_text(f"没有找到群号为 {number} 的图片。")
            return
    else:
        # Get a random open image
        image = db.get_random_open_image()
        if not image:
            # If no open images, just get any image
            image = images[0]
            logger.info(f"No open images, using first available: {image['image_id']}")
        else:
            logger.info(f"Using random open image: {image['image_id']}")
    
    # Send the image
    try:
        # If replying to someone, send as reply
        reply_to_id = update.message.reply_to_message.message_id if update.message.reply_to_message else None
        
        sent_msg = context.bot.send_photo(
            chat_id=chat_id,
            photo=image['file_id'],
            caption=f"🌟 群: {image['number']} 🌟",
            reply_to_message_id=reply_to_id
        )
        logger.info(f"Admin manually sent image {image['image_id']} with number {image['number']}")
    except Exception as e:
        logger.error(f"Error sending image: {e}")
        update.message.reply_text(f"发送图片错误: {e}")
        return
    
    # Option to forward to Group B if admin adds "转发" in command
    if "转发" in full_text:
        try:
            # Get a target Group B
            if GROUP_B_IDS:
                target_group_b = list(GROUP_B_IDS)[0]  # Use first Group B
                
                # Extract amount from message if present
                amount_match = re.search(r'金额(\d+)', full_text) 
                amount = amount_match.group(1) if amount_match else "0"
                
                # Forward to Group B
                forwarded = context.bot.send_message(
                    chat_id=target_group_b,
                    text=f"💰 金额：{amount}\n🔢 群：{image['number']}\n\n❌ 如果会员10分钟没进群请回复0"
                )
                
                # Store mapping for responses
                forwarded_msgs[image['image_id']] = {
                    'group_a_msg_id': sent_msg.message_id,
                    'group_a_chat_id': chat_id,
                    'group_b_msg_id': forwarded.message_id,
                    'group_b_chat_id': target_group_b,
                    'image_id': image['image_id'],
                    'amount': amount,
                    'number': str(image['number']),
                    'original_user_id': user_id,
                    'original_message_id': update.message.message_id
                }
                
                save_persistent_data()
                logger.info(f"Admin forwarded image {image['image_id']} to Group B {target_group_b}")
                
                # Only set image to closed if explicitly requested to avoid confusion
                if "关闭" in full_text:
                    db.set_image_status(image['image_id'], "closed")
                    logger.info(f"Admin closed image {image['image_id']}")
            else:
                update.message.reply_text("没有设置群B，无法转发。")
        except Exception as e:
            logger.error(f"Error forwarding to Group B: {e}")
            update.message.reply_text(f"转发至群B失败: {e}")

def handle_reset_specific_image(update: Update, context: CallbackContext) -> None:
    """Handle command to reset a specific image by its number."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    message_text = update.message.text.strip()
    
    # Check if this is Group B
    if chat_id not in GROUP_B_IDS and chat_id != GROUP_B_ID:
        logger.info(f"Reset specific image command used in non-Group B chat: {chat_id}")
        return
    
    # Extract the image number from the command "重置群{number}"
    match = re.search(r'^重置群(\d+)$', message_text)
    if not match:
        return
    
    image_number = int(match.group(1))
    logger.info(f"Reset command for image number {image_number} detected in Group B {chat_id}")
    
    # Check if user is a group admin or global admin
    if not is_group_admin(user_id, chat_id) and not is_global_admin(user_id):
        logger.info(f"User {user_id} tried to reset image but is not an admin")
        update.message.reply_text("只有群操作人或全局管理员可以重置群码。")
        return
    
    logger.info(f"Admin {user_id} is resetting image number {image_number} in Group B: {chat_id}")
    
    # Get image count before deletion
    all_images = db.get_all_images()
    before_count = len(all_images)
    logger.info(f"Total images in database before reset: {before_count}")
    
    # Delete the specific image by its number
    success = db.delete_image_by_number(image_number, chat_id)
    
    if success:
        # Also clear related message mappings for this image
        global forwarded_msgs, group_b_responses
        
        # Find any message mappings related to this image
        mappings_to_remove = []
        for img_id, data in forwarded_msgs.items():
            if data.get('number') == str(image_number) and data.get('group_b_chat_id') == chat_id:
                mappings_to_remove.append(img_id)
                logger.info(f"Found matching mapping for image {img_id} with number {image_number}")
        
        # Remove the found mappings
        for img_id in mappings_to_remove:
            if img_id in forwarded_msgs:
                logger.info(f"Removing forwarded message mapping for {img_id}")
                del forwarded_msgs[img_id]
            if img_id in group_b_responses:
                logger.info(f"Removing group B response for {img_id}")
                del group_b_responses[img_id]
        
        save_persistent_data()
        
        # Get image count after deletion
        remaining_images = db.get_all_images()
        after_count = len(remaining_images)
        deleted_count = before_count - after_count
        
        # Provide feedback to the user
        if deleted_count > 0:
            update.message.reply_text(f"✅ 已重置群码 {image_number}，删除了 {deleted_count} 张图片。")
            logger.info(f"Successfully reset image number {image_number}")
        else:
            update.message.reply_text(f"⚠️ 未找到群号为 {image_number} 的图片，或者删除操作失败。")
            logger.warning(f"No images with number {image_number} were deleted")
    else:
        update.message.reply_text(f"❌ 重置群码 {image_number} 失败。未找到匹配的图片。")
        logger.error(f"Failed to reset image number {image_number}")

if __name__ == '__main__':
    main() 
