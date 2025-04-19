# Telegram Image Management Bot

This bot manages images between two Telegram groups, with status tracking functionality.

## Features

- Set images with associated numbers
- Track "open" and "closed" status for each image
- Forward messages between two groups
- Randomly select open images when users request them
- Respond with "Full" when all images are closed

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Set environment variables:
   ```
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export GROUP_A_ID="group_a_chat_id"
   export GROUP_B_ID="group_b_chat_id"
   ```

   For Windows:
   ```
   set TELEGRAM_BOT_TOKEN=your_bot_token
   set GROUP_A_ID=group_a_chat_id
   set GROUP_B_ID=group_b_chat_id
   ```

3. Run the bot:
   ```
   python bot.py
   ```

## Usage

### Admin Commands (in private chat with bot)

- `/start` - Start the bot
- `/help` - Show help message
- `/setimage <number>` - Set an image with a number (reply to an image)
- `/images` - List all images and their statuses

### Group A Functionality

- When a user sends a message containing only a number (e.g., "50", "100"), the bot will:
  - Check if any images are in "open" status
  - If all images are closed, reply with "Full"
  - If at least one image is open, randomly select an open image and send it
  - Forward the message and image to Group B
  - Set the image status to "closed"

### Group B Functionality

- When an image is forwarded from Group A, users can:
  - Click the "+" button below the image
  - Reply to the image with a message starting with "+" (e.g., "+50")
  - This will set the image status back to "open"

## How It Works

1. Images are set by admins with associated numbers
2. Each image has a status (open/closed)
3. Group A users request images by sending number messages
4. The bot selects random open images to respond with
5. After sending an image, it's marked as closed
6. Group B users can reopen images using the + button or replies

## Database

Images and their statuses are stored in `image_db.json` in the following format:

```json
{
  "images": [
    {
      "image_id": "img_1",
      "number": 50,
      "file_id": "telegram_file_id",
      "status": "open"
    }
  ]
}
``` 