"""
Databricks Genie API Client for conversational interactions
"""
import time
import logging
from typing import Optional, Dict, Any, List
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class DatabricksGenieClient:
    """
    Client for interacting with Databricks Genie conversational APIs.
    
    This client uses the Databricks SDK with automatic OAuth M2M (machine-to-machine) 
    authentication via service principals.
    """
    
    def __init__(self, space_id: str):
        """
        Initialize the Databricks Genie client using Databricks SDK with OAuth M2M authentication.
        
        Args:
            space_id: Genie space ID to use for conversations
        
        Service Principal Authentication:
            When you create a Databricks App, Databricks automatically provisions a dedicated 
            service principal for that app. This client leverages that for authentication.
            
            Key facts:
            - ✅ Service principals are automatically provisioned when creating apps
            - ✅ Each app gets its own unique service principal (cannot reuse existing ones)
            - ✅ OAuth Client ID and Secret are found in the app's Authorization tab
            - ✅ The Databricks SDK automatically reads these credentials at runtime
            - ✅ OAuth tokens are managed automatically (no manual handling needed)
        
        Authentication Flow:
            **In Databricks Apps (Recommended for Production):**
            1. You create a Databricks App → service principal auto-provisioned
            2. Platform provides DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET
            3. SDK detects app environment and uses OAuth 2.0 M2M authentication
            4. All API calls use: Authorization: Bearer <oauth_access_token>
            5. Token refresh is handled automatically
            
            **In Local Development:**
            - Set DATABRICKS_HOST and DATABRICKS_TOKEN in environment (.env file)
            - The SDK reads these and authenticates with personal access token
            - Useful for testing before deployment
        
        Permissions Required:
            The app's service principal must have explicit permissions:
            - CAN USE privileges on the SQL warehouse used by Genie
            - SELECT permissions on Unity Catalog tables
            - USE SCHEMA and USE CATALOG permissions
            - Access to the Genie space itself
            
            Note: Service principal authorization operates independently of user-level 
            permissions. All app users share the same permissions as the app's principal.
        
        For detailed setup instructions, see:
            - SETUP_CHECKLIST.md for step-by-step setup
            - PERMISSIONS_SETUP_GUIDE.md for permission configuration
        """
        self.space_id = space_id
        
        # Initialize Databricks SDK WorkspaceClient
        # The SDK automatically detects the environment and uses appropriate authentication:
        # 
        # In Databricks Apps (Production):
        #   - Reads DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET (auto-provided by platform)
        #   - Uses OAuth 2.0 M2M (machine-to-machine) authentication
        #   - Service principal was auto-provisioned when the app was created
        #   - All API calls include: Authorization: Bearer <oauth_access_token>
        #   - Token refresh happens automatically
        # 
        # In Local Development:
        #   - Reads DATABRICKS_HOST and DATABRICKS_TOKEN from environment
        #   - Uses personal access token authentication
        #   - Useful for testing before deploying to Databricks Apps
        logger.info("Initializing Databricks SDK with OAuth M2M authentication")
        self.workspace_client = WorkspaceClient()
        
        # Get the API client which handles all HTTP requests with automatic authentication
        # The api_client.do() method automatically:
        #   - Adds OAuth Bearer tokens to all requests (in Databricks Apps)
        #   - Handles token refresh when needed
        #   - Uses personal access token (in local dev)
        self.api_client = self.workspace_client.api_client
        
        # Get host from workspace client config
        self.host = self.workspace_client.config.host.rstrip('/')
        
        logger.info(f"✓ Connected to Databricks workspace: {self.host}")
        logger.info(f"✓ Using OAuth M2M authentication via app service principal")
        logger.info(f"✓ Genie space ID: {self.space_id}")
        
        self.base_url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}"
    
    def _make_request(self, method: str, path: str, data: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """
        Make an authenticated API request using the SDK's HTTP client.
        
        The SDK automatically handles authentication:
        - In Databricks Apps: Uses OAuth M2M with service principal (auto-provisioned)
        - In Local Dev: Uses personal access token from environment
        - All requests automatically include: Authorization: Bearer <access_token>
        - Token refresh is handled automatically when needed
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., "/api/2.0/genie/spaces/{space_id}/start-conversation")
            data: Optional request body data
            
        Returns:
            Response dict if successful, None otherwise
        
        Example:
            response = self._make_request("POST", 
                                          "/api/2.0/genie/spaces/01f0.../start-conversation",
                                          data={"content": "Show sales data"})
        """
        try:
            # The SDK's do() method expects 'body' parameter, not 'data'
            response = self.api_client.do(method, path, body=data)
            return response
        except Exception as e:
            logger.error(f"API request failed: {method} {path} - {e}")
            return None
    
    def create_conversation(self) -> Optional[str]:
        """
        Create a new conversation in the Genie space
        Note: Conversations are created when you send the first message via start-conversation
        
        Returns:
            None (conversation will be created with first message)
        """
        # Return None - conversation will be created when first message is sent
        logger.info(f"New conversation will be created with first message")
        return None
    
    def send_message(self, conversation_id: str, message: str) -> Optional[Dict[str, Any]]:
        """
        Send a message to the Genie space
        
        Args:
            conversation_id: The conversation ID (optional, for continuing a conversation)
            message: The user's message/question
            
        Returns:
            Message response dict if successful, None otherwise
        """
        # Determine the correct endpoint based on whether this is a new or existing conversation
        if conversation_id:
            # Continue existing conversation
            path = f"/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages"
        else:
            # Start new conversation
            path = f"/api/2.0/genie/spaces/{self.space_id}/start-conversation"
        
        payload = {"content": message}
        
        result = self._make_request("POST", path, data=payload)
        
        if not result:
            return None
        
        message_id = result.get("message_id") or result.get("id")
        
        # Extract message details if nested
        message_data = result.get("message", {})
        if message_data:
            actual_conv_id = message_data.get("conversation_id")
            message_id = message_data.get("id") or message_id
        else:
            actual_conv_id = result.get("conversation_id", conversation_id)
        
        logger.info(f"Sent message {message_id} to conversation {actual_conv_id}")
        
        # Return the message data with conversation_id at top level for easy access
        return {
            "id": message_id,
            "message_id": message_id,
            "conversation_id": actual_conv_id,
            "status": message_data.get("status") or result.get("status"),
            "content": message_data.get("content") or result.get("content"),
            "raw_response": result
        }
    
    def get_message_status(self, conversation_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status and response of a message
        
        Args:
            conversation_id: The conversation ID
            message_id: The message ID
            
        Returns:
            Message status dict if successful, None otherwise
        """
        path = f"/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages/{message_id}"
        
        result = self._make_request("GET", path)
        
        if not result:
            return None
        
        # Handle both direct message response and nested message data
        if "message" in result:
            return result["message"]
        return result
    
    def wait_for_response(
        self, 
        conversation_id: str, 
        message_id: str, 
        max_wait_time: int = 60,
        poll_interval: int = 2
    ) -> Optional[Dict[str, Any]]:
        """
        Poll for a message response until it's complete or timeout
        
        Args:
            conversation_id: The conversation ID
            message_id: The message ID
            max_wait_time: Maximum time to wait in seconds
            poll_interval: Time between polls in seconds
            
        Returns:
            Complete message response dict if successful, None otherwise
        """
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            status = self.get_message_status(conversation_id, message_id)
            
            if not status:
                return None
            
            # Check if the response is complete
            state = status.get("status")
            
            if state == "COMPLETED":
                logger.info(f"Message {message_id} completed")
                return status
            elif state in ["FAILED", "CANCELLED"]:
                logger.error(f"Message {message_id} failed with state: {state}")
                return status
            
            time.sleep(poll_interval)
        
        logger.warning(f"Timeout waiting for message {message_id}")
        return None
    
    def get_statement_result(self, statement_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the actual query result data from a SQL statement
        
        Args:
            statement_id: The SQL statement ID
            
        Returns:
            Statement result dict with data if successful, None otherwise
        """
        path = f"/api/2.0/sql/statements/{statement_id}"
        
        result = self._make_request("GET", path)
        
        if result:
            logger.info(f"Retrieved statement result for {statement_id}")
        
        return result
    
    def ask_question(self, question: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        High-level method to ask a question and get the response
        
        Args:
            question: The question to ask
            conversation_id: Optional existing conversation ID. If None, creates a new one.
            
        Returns:
            Dict with 'success', 'conversation_id', 'response', and 'attachments' keys
        """
        # Send the message (conversation will be created implicitly if conversation_id is None)
        message_result = self.send_message(conversation_id, question)
        if not message_result:
            return {
                "success": False,
                "conversation_id": conversation_id,
                "error": "Failed to send message"
            }
        
        # Get the actual conversation ID from the response (API might return it)
        actual_conversation_id = message_result.get("conversation_id", conversation_id)
        message_id = message_result.get("id") or message_result.get("message_id")
        
        # Wait for the response
        response = self.wait_for_response(actual_conversation_id, message_id)
        
        if not response:
            return {
                "success": False,
                "conversation_id": actual_conversation_id,
                "error": "Failed to get response or timeout"
            }
        
        # Extract the response content
        status = response.get("status")
        
        if status == "COMPLETED":
            # Extract text response and any attachments
            attachments = response.get("attachments", [])
            query_result = response.get("query_result")
            
            # Build response text from attachments
            # The actual answer is in various attachment types
            response_text = ""
            statement_id = None
            
            if attachments:
                # Try to extract information from various attachment types
                for attachment in attachments:
                    # Text attachments (explanations, answers)
                    if "text" in attachment:
                        text_content = attachment["text"].get("content", "")
                        if text_content:
                            response_text += text_content + "\n\n"
                    
                    # Query attachments (SQL queries with descriptions)
                    elif "query" in attachment:
                        query_data = attachment["query"]
                        description = query_data.get("description", "")
                        statement_id = query_data.get("statement_id")
                        
                        if description:
                            response_text += description + "\n\n"
                        
                        # SQL query is not displayed per user request
            
            # Fetch actual query result data if statement_id is present
            result_data = None
            if statement_id:
                statement_result = self.get_statement_result(statement_id)
                if statement_result:
                    # Include both result data and schema
                    result_data = {
                        "data": statement_result.get("result", {}),
                        "schema": statement_result.get("manifest", {}).get("schema", {})
                    }
            
            # Fallback to content if no attachments with text
            if not response_text.strip():
                response_text = response.get("content", "No response generated")
            
            # Extract suggested questions for follow-up
            suggested_questions = response.get("suggested_questions", [])
            
            return {
                "success": True,
                "conversation_id": actual_conversation_id,
                "message_id": message_id,  # Include message_id for feedback
                "response": response_text.strip(),
                "attachments": attachments,
                "query_result": query_result,
                "result_data": result_data,  # Actual query result rows
                "suggested_questions": suggested_questions  # Follow-up questions
            }
        else:
            error_msg = response.get("error", {}).get("message", "Unknown error")
            return {
                "success": False,
                "conversation_id": actual_conversation_id,
                "error": f"Query failed: {error_msg}"
            }
    
    def get_conversation_history(self, conversation_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get the message history for a conversation
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            List of message dicts if successful, None otherwise
        """
        path = f"/api/2.0/genie/spaces/{self.space_id}/messages?conversation_id={conversation_id}"
        
        result = self._make_request("GET", path)
        
        if result:
            return result.get("messages", [])
        
        return None
    
    def send_message_feedback(
        self, 
        conversation_id: str, 
        message_id: str, 
        rating: str,
        feedback_text: Optional[str] = None
    ) -> bool:
        """
        Send feedback for a message
        
        Args:
            conversation_id: The conversation ID
            message_id: The message ID
            rating: Feedback rating - "positive", "negative", or "none" (case-insensitive)
            feedback_text: Optional feedback text
            
        Returns:
            True if feedback was sent successfully, False otherwise
        """
        path = f"/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages/{message_id}/feedback"
        
        # API requires uppercase rating values: POSITIVE, NEGATIVE, or NONE
        payload = {
            "rating": rating.upper()
        }
        
        if feedback_text:
            payload["feedback_text"] = feedback_text
        
        result = self._make_request("POST", path, data=payload)
        
        if result is not None:
            logger.info(f"Sent {rating.upper()} feedback for message {message_id}")
            return True
        
        return False

