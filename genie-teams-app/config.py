"""
Configuration Management
Loads environment variables for the application
"""
import os
from typing import Optional


class Config:
    """Application configuration"""
    
    # Databricks Configuration (Azure AD Service Principal)
    DATABRICKS_HOST: str = os.getenv("DATABRICKS_HOST", "")
    DATABRICKS_CLIENT_ID: str = os.getenv("DATABRICKS_CLIENT_ID", "")
    DATABRICKS_CLIENT_SECRET: str = os.getenv("DATABRICKS_CLIENT_SECRET", "")
    DATABRICKS_TENANT_ID: str = os.getenv("DATABRICKS_TENANT_ID", "")
    DATABRICKS_GENIE_SPACE_ID: str = os.getenv("DATABRICKS_GENIE_SPACE_ID", "")
    
    # Microsoft Teams Bot Configuration
    MICROSOFT_APP_ID: str = os.getenv("MICROSOFT_APP_ID", "")
    MICROSOFT_APP_PASSWORD: str = os.getenv("MICROSOFT_APP_PASSWORD", "")
    MICROSOFT_APP_TENANT_ID: str = os.getenv("MICROSOFT_APP_TENANT_ID", "")
    
    # Application Settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        required = [
            ("DATABRICKS_HOST", cls.DATABRICKS_HOST),
            ("DATABRICKS_CLIENT_ID", cls.DATABRICKS_CLIENT_ID),
            ("DATABRICKS_CLIENT_SECRET", cls.DATABRICKS_CLIENT_SECRET),
            ("DATABRICKS_TENANT_ID", cls.DATABRICKS_TENANT_ID),
            ("DATABRICKS_GENIE_SPACE_ID", cls.DATABRICKS_GENIE_SPACE_ID),
            ("MICROSOFT_APP_ID", cls.MICROSOFT_APP_ID),
            ("MICROSOFT_APP_PASSWORD", cls.MICROSOFT_APP_PASSWORD),
        ]
        
        missing = [name for name, value in required if not value]
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        
        return True
