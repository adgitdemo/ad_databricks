"""
Configuration management for the Databricks Genie Slack App
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Application configuration"""
    
    # Slack Configuration
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
    SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
    SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
    
    # Databricks Configuration
    # Note: DATABRICKS_HOST and authentication are handled automatically by Databricks SDK
    # For Databricks Apps: SDK uses the app's service principal automatically
    # For local dev: SDK reads DATABRICKS_HOST and DATABRICKS_TOKEN from environment
    DATABRICKS_GENIE_SPACE_ID = os.getenv("DATABRICKS_GENIE_SPACE_ID")
    
    # App Configuration
    PORT = int(os.getenv("PORT", "3000"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls):
        """Validate that all required configuration is present"""
        required_vars = [
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET",
            "SLACK_APP_TOKEN",
            "DATABRICKS_GENIE_SPACE_ID"
        ]
        
        missing = [var for var in required_vars if not getattr(cls, var)]
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        # Note: DATABRICKS_HOST and auth credentials are validated by Databricks SDK
        # The SDK will raise appropriate errors if they're missing
        
        return True

