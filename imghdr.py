"""
Simple imghdr replacement module.
This is a minimal implementation to make python-telegram-bot work without the standard library imghdr.
"""

def what(file, h=None):
    """
    Simplified version of imghdr.what that returns 'jpeg' as a fallback.
    """
    # Just return a common image type to make the telegram library work
    return 'jpeg' 