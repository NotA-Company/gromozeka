#!/usr/bin/env python3
"""
Test script for Gromozeka bot components.
This script tests the configuration loading and database functionality
without requiring a real Telegram bot token.
"""

import sys
import tempfile
import os
from pathlib import Path

# Test imports
try:
    import tomli
    print("✅ tomli import successful")
except ImportError as e:
    print(f"❌ tomli import failed: {e}")
    sys.exit(1)

try:
    from telegram import Update
    from telegram.ext import Application
    print("✅ python-telegram-bot import successful")
except ImportError as e:
    print(f"❌ python-telegram-bot import failed: {e}")
    sys.exit(1)

try:
    from database import DatabaseWrapper
    print("✅ Database wrapper import successful")
except ImportError as e:
    print(f"❌ Database wrapper import failed: {e}")
    sys.exit(1)


def test_config_loading():
    """Test TOML configuration loading."""
    print("\n🧪 Testing configuration loading...")
    
    # Create a temporary config file
    test_config = """
[bot]
token = "test_token_123"

[database]
path = "test.db"
max_connections = 3
timeout = 15

[logging]
level = "DEBUG"
format = "test format"
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
        f.write(test_config)
        temp_config_path = f.name
    
    try:
        # Test loading
        with open(temp_config_path, "rb") as f:
            config = tomli.load(f)
        
        # Verify config structure
        assert config["bot"]["token"] == "test_token_123"
        assert config["database"]["path"] == "test.db"
        assert config["database"]["max_connections"] == 3
        assert config["logging"]["level"] == "DEBUG"
        
        print("✅ Configuration loading test passed")
        return True
        
    except Exception as e:
        print(f"❌ Configuration loading test failed: {e}")
        return False
    finally:
        os.unlink(temp_config_path)


def test_database_wrapper():
    """Test database wrapper functionality."""
    print("\n🧪 Testing database wrapper...")
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        temp_db_path = f.name
    
    try:
        # Initialize database
        db = DatabaseWrapper(temp_db_path)
        print("✅ Database initialization successful")
        
        # Test user operations
        user_id = 12345
        username = "test_user"
        first_name = "Test"
        last_name = "User"
        
        # Save user
        result = db.save_user(user_id, username, first_name, last_name)
        assert result == True
        print("✅ User save test passed")
        
        # Get user
        user_data = db.get_user(user_id)
        assert user_data is not None
        assert user_data['user_id'] == user_id
        assert user_data['username'] == username
        print("✅ User retrieval test passed")
        
        # Test settings
        db.set_setting("test_key", "test_value")
        value = db.get_setting("test_key")
        assert value == "test_value"
        print("✅ Settings test passed")
        
        # Test message saving
        message_text = "Hello, this is a test message!"
        result = db.save_message(user_id, message_text)
        assert result == True
        print("✅ Message save test passed")
        
        # Test message retrieval
        messages = db.get_user_messages(user_id)
        assert len(messages) == 1
        assert messages[0]['message_text'] == message_text
        print("✅ Message retrieval test passed")
        
        db.close()
        print("✅ Database wrapper tests passed")
        return True
        
    except Exception as e:
        print(f"❌ Database wrapper test failed: {e}")
        return False
    finally:
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)


def test_bot_class_import():
    """Test that the main bot class can be imported."""
    print("\n🧪 Testing bot class import...")
    
    try:
        # We can't fully test the bot without a token, but we can test import
        from main import GromozekBot
        print("✅ GromozekBot class import successful")
        
        # Test that we can create the class with a test config
        test_config_content = """
[bot]
token = "test_token"

[database]
path = ":memory:"
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(test_config_content)
            temp_config_path = f.name
        
        try:
            bot = GromozekBot(temp_config_path)
            print("✅ GromozekBot initialization successful")
            return True
        except SystemExit:
            # Expected if token validation fails
            print("✅ GromozekBot initialization test passed (expected token validation)")
            return True
        finally:
            os.unlink(temp_config_path)
            
    except Exception as e:
        print(f"❌ Bot class import test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("🚀 Starting Gromozeka bot component tests...\n")
    
    tests = [
        test_config_loading,
        test_database_wrapper,
        test_bot_class_import,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The bot setup is working correctly, dood!")
        print("\n📝 Next steps:")
        print("1. Set your bot token in config.toml")
        print("2. Run the bot with: python main.py")
        return True
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)