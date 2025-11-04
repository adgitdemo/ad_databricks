"""
Databricks Genie API Client
Handles communication with Databricks Genie conversational API
"""
import logging
import json
import aiohttp
import requests
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Feedback ratings for Genie API (must be UPPERCASE)
FEEDBACK_POSITIVE = "POSITIVE"
FEEDBACK_NEGATIVE = "NEGATIVE"


class GenieClient:
    """Client for interacting with Databricks Genie using HTTP API"""
    
    def __init__(self, host: str, client_id: str, client_secret: str, tenant_id: str, space_id: str):
        """
        Initialize Genie client using Azure AD service principal credentials.
        
        Args:
            host: Databricks workspace URL
            client_id: Azure AD application (service principal) ID
            client_secret: Azure AD application secret
            tenant_id: Azure AD tenant ID
            space_id: Genie space ID
        """
        self.host = host.rstrip("/")
        self.space_id = space_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.token_endpoint = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        self.scope = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default"
        self._access_token = None
        self._token_expires_at = 0

        logger.info(f"Initialized Genie client for space: {space_id}")

    def _get_headers(self) -> Dict[str, str]:
        """Retrieve authorization headers using cached client credential token."""
        now = time.time()
        if not self._access_token or now > (self._token_expires_at - 60):
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            }
            response = requests.post(self.token_endpoint, data=data, timeout=10)
            response.raise_for_status()
            token_result = response.json()
            access_token = token_result.get("access_token")
            if not access_token:
                raise RuntimeError(f"Failed to obtain Databricks access token: {token_result}")
            expires_in = int(token_result.get("expires_in", 3600))
            self._access_token = access_token
            self._token_expires_at = now + expires_in
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json"
        }


    
    async def ask_question(self, question: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Ask a question to Genie
        
        Args:
            question: User's question
            conversation_id: Optional conversation ID for context
            
        Returns:
            Dictionary with response data
        """
        try:
            logger.info(f"Asking Genie: {question[:100]}...")
            
            # Start a new conversation
            url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}/start-conversation"
            payload = {"content": question}
            headers = self._get_headers()
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status >= 400:
                        # Capture error details from response body
                        error_body = await response.text()
                        try:
                            error_json = json.loads(error_body)
                            error_msg = error_json.get("message", error_body)
                            error_code = error_json.get("error_code", "")
                            logger.error(f"Genie API error {response.status}: {error_code} - {error_msg}")
                            logger.error(f"Full error response: {error_body}")
                            
                            # Provide helpful error messages based on status
                            if response.status == 400:
                                return {
                                    "status": "error",
                                    "error": f"Bad Request: {error_msg}",
                                    "response": (
                                        f"❌ Databricks Genie Error:\n\n"
                                        f"{error_msg}\n\n"
                                        f"**Possible causes:**\n"
                                        f"• The Genie space ID '{self.space_id}' may be invalid\n"
                                        f"• The service principal may not have access to this space\n"
                                        f"• The request format may be incorrect\n\n"
                                        f"Please verify:\n"
                                        f"1. Space ID is correct in your Function App settings\n"
                                        f"2. Service principal is registered in Databricks Admin Console\n"
                                        f"3. Service principal has 'Can use' permission on the Genie space"
                                    )
                                }
                            elif response.status == 401:
                                return {
                                    "status": "error",
                                    "error": f"Unauthorized: {error_msg}",
                                    "response": (
                                        f"❌ Authentication failed:\n\n"
                                        f"{error_msg}\n\n"
                                        f"Please verify:\n"
                                        f"• Service principal credentials (CLIENT_ID, CLIENT_SECRET, TENANT_ID) are correct\n"
                                        f"• Service principal has 'Azure Databricks' API permission\n"
                                        f"• Admin consent has been granted for the API permission"
                                    )
                                }
                            elif response.status == 403:
                                return {
                                    "status": "error",
                                    "error": f"Forbidden: {error_msg}",
                                    "response": (
                                        f"❌ Access denied:\n\n"
                                        f"{error_msg}\n\n"
                                        f"The service principal does not have permission to access this Genie space.\n\n"
                                        f"Please:\n"
                                        f"1. Go to Databricks Admin Console → Service Principals\n"
                                        f"2. Find or add service principal: {self.client_id}\n"
                                        f"3. Go to Genie space settings and grant 'Can use' permission"
                                    )
                                }
                            elif response.status == 404:
                                return {
                                    "status": "error",
                                    "error": f"Not Found: {error_msg}",
                                    "response": (
                                        f"❌ Resource not found:\n\n"
                                        f"{error_msg}\n\n"
                                        f"The Genie space '{self.space_id}' was not found.\n"
                                        f"Please verify the DATABRICKS_GENIE_SPACE_ID in your Function App settings."
                                    )
                                }
                            else:
                                return {
                                    "status": "error",
                                    "error": f"HTTP {response.status}: {error_msg}",
                                    "response": f"❌ Databricks Genie Error ({response.status}):\n\n{error_msg}"
                                }
                        except json.JSONDecodeError:
                            logger.error(f"Non-JSON error response: {error_body}")
                            return {
                                "status": "error",
                                "error": f"HTTP {response.status}: {error_body}",
                                "response": f"❌ Databricks Genie Error ({response.status}):\n\n{error_body[:500]}"
                            }
                    
                    response.raise_for_status()
                    data = await response.json()
            
            conv_id = data.get("conversation_id", "")
            msg_id = data.get("message_id", "")
            
            if not conv_id or not msg_id:
                logger.error("No conversation_id or message_id in response")
                return {
                    "status": "error",
                    "error": "Invalid response from Genie API",
                    "response": "Sorry, I couldn't start a conversation with Genie."
                }
            
            # Poll for the actual response
            response_text = await self._poll_for_response(conv_id, msg_id)
            
            result = {
                "conversation_id": conv_id,
                "message_id": msg_id,
                "response": response_text,
                "status": "success"
            }
            
            logger.info(f"Genie response received: {response_text[:200]}...")
            return result
            
        except aiohttp.ClientResponseError as e:
            logger.error(f"Genie API HTTP error: {e.status} - {e.message}")
            return {
                "status": "error",
                "error": f"HTTP {e.status}: {e.message}",
                "response": f"Sorry, I encountered an error contacting Databricks Genie. Please try again."
            }
        except Exception as e:
            logger.error(f"Error asking Genie: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "response": f"Sorry, I encountered an error: {str(e)}"
            }
    
    async def continue_conversation(self, conversation_id: str, question: str) -> Dict[str, Any]:
        """
        Continue an existing conversation
        
        Args:
            conversation_id: Existing conversation ID
            question: Follow-up question
            
        Returns:
            Dictionary with response data
        """
        try:
            logger.info(f"Continuing conversation {conversation_id}")
            
            url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages"
            payload = {"content": question}
            headers = self._get_headers()
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status >= 400:
                        # Capture error details from response body
                        error_body = await response.text()
                        try:
                            error_json = json.loads(error_body)
                            error_msg = error_json.get("message", error_body)
                            error_code = error_json.get("error_code", "")
                            logger.error(f"Genie API error {response.status}: {error_code} - {error_msg}")
                            logger.error(f"Full error response: {error_body}")
                            
                            # Provide helpful error messages
                            if response.status == 400:
                                return {
                                    "status": "error",
                                    "error": f"Bad Request: {error_msg}",
                                    "response": f"❌ Error continuing conversation:\n\n{error_msg}"
                                }
                            elif response.status == 404:
                                return {
                                    "status": "error",
                                    "error": f"Not Found: {error_msg}",
                                    "response": (
                                        f"❌ Conversation not found:\n\n"
                                        f"The conversation may have expired or been deleted.\n"
                                        f"Please start a new conversation."
                                    )
                                }
                            else:
                                return {
                                    "status": "error",
                                    "error": f"HTTP {response.status}: {error_msg}",
                                    "response": f"❌ Databricks Genie Error ({response.status}):\n\n{error_msg}"
                                }
                        except json.JSONDecodeError:
                            logger.error(f"Non-JSON error response: {error_body}")
                            return {
                                "status": "error",
                                "error": f"HTTP {response.status}: {error_body}",
                                "response": f"❌ Databricks Genie Error ({response.status}):\n\n{error_body[:500]}"
                            }
                    
                    response.raise_for_status()
                    data = await response.json()
            
            msg_id = data.get("message_id", "")
            
            # Poll for the actual response
            response_text = await self._poll_for_response(conversation_id, msg_id)
            
            result = {
                "conversation_id": conversation_id,
                "message_id": msg_id,
                "response": response_text,
                "status": "success"
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error continuing conversation: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "response": f"Sorry, I encountered an error: {str(e)}"
            }
    
    async def send_feedback(self, conversation_id: str, message_id: str, rating: str) -> Dict[str, Any]:
        """
        Send feedback for a Genie message
        
        Args:
            conversation_id: Conversation ID
            message_id: Message ID to provide feedback for
            rating: "positive" or "negative"
            
        Returns:
            Dictionary with status
        """
        try:
            url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages/{message_id}/feedback"
            
            # Databricks API requires UPPERCASE rating values
            rating_upper = rating.upper()
            payload = {"rating": rating_upper}
            
            logger.info(f"Sending {rating_upper} feedback for message {message_id}")
            
            headers = self._get_headers()

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    logger.info(f"Feedback sent successfully to Genie")
                    return {"status": "success"}
                    
        except Exception as e:
            logger.error(f"❌ Error sending feedback: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def _poll_for_response(self, conversation_id: str, message_id: str, max_attempts: int = 30, delay: float = 2.0) -> str:
        """
        Poll for Genie's response to a message
        
        Args:
            conversation_id: Conversation ID
            message_id: Message ID to poll for
            max_attempts: Maximum number of polling attempts
            delay: Delay between polls in seconds
            
        Returns:
            Response text from Genie
        """
        import asyncio
        
        url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages/{message_id}"
        
        logger.info(f"Polling for response to message {message_id}...")
        
        headers = self._get_headers()

        async with aiohttp.ClientSession() as session:
            for attempt in range(max_attempts):
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        response.raise_for_status()
                        data = await response.json()
                    
                    # Check if we have a response from Genie
                    status = data.get("status", "")
                    
                    if status in ["COMPLETED", "SUCCESS", "FINISHED"]:
                        # Fetch attachment query results if any
                        response_text = await self._extract_response_with_attachments(session, conversation_id, message_id, data)
                        return response_text
                    
                    elif status in ["FAILED", "ERROR"]:
                        error_msg = data.get("error", {}).get("message", "Unknown error")
                        logger.error(f"Genie returned error: {error_msg}")
                        return f"Sorry, Genie encountered an error: {error_msg}"
                    
                    elif status in ["EXECUTING", "QUERYING_HISTORY", "RUNNING", "PENDING"]:
                        # Still processing, wait and retry
                        logger.info(f"Still processing (status: {status}), waiting {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    
                    else:
                        # Unknown status or no status, log and retry
                        logger.warning(f"Unknown status '{status}', response: {json.dumps(data, indent=2)[:500]}")
                        await asyncio.sleep(delay)
                        continue
                        
                except Exception as e:
                    logger.error(f"Error polling for response (attempt {attempt + 1}): {str(e)}")
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise
            
            # Exceeded max attempts
            logger.error(f"Exceeded max polling attempts ({max_attempts})")
            return "Sorry, Genie is taking too long to respond. Please try again."
    
    async def _extract_response_with_attachments(self, session: aiohttp.ClientSession, conversation_id: str, message_id: str, message_data: Dict[str, Any]) -> str:
        """
        Extract response text and fetch attachment query results
        
        Args:
            session: aiohttp session
            conversation_id: Conversation ID
            message_id: Message ID
            message_data: Message data from getMessage API
            
        Returns:
            Complete response with attachment results
        """
        parts = []
        user_question = message_data.get("content", "")  # Store to filter out later
        
        # Fetch query results from attachments (these are the actual responses)
        if "attachments" in message_data and message_data["attachments"]:
            for attachment in message_data["attachments"]:
                if not isinstance(attachment, dict):
                    continue
                
                # Extract Genie's explanation from query.description
                text_content = None
                
                if "query" in attachment and isinstance(attachment["query"], dict):
                    query_obj = attachment["query"]
                    if "description" in query_obj and query_obj["description"]:
                        text_content = query_obj["description"]
                
                # Try text field as fallback
                if not text_content and "text" in attachment:
                    text_obj = attachment["text"]
                    if isinstance(text_obj, dict) and "content" in text_obj:
                        text_content = text_obj["content"]
                    elif isinstance(text_obj, str):
                        text_content = text_obj
                
                # Add explanation if found and not the user's question
                if text_content and text_content != user_question and len(text_content) > 10:
                    parts.append(text_content)
                
                # Fetch query result data
                attachment_id = attachment.get("attachment_id") or attachment.get("id")
                if attachment_id:
                    try:
                        result_url = f"{self.host}/api/2.0/genie/spaces/{self.space_id}/conversations/{conversation_id}/messages/{message_id}/attachments/{attachment_id}/query-result"
                        
                        result_headers = self._get_headers()
                        async with session.get(result_url, headers=result_headers, timeout=aiohttp.ClientTimeout(total=10)) as result_response:
                            if result_response.status == 200:
                                result_data = await result_response.json()
                                query_result_text = self._format_query_result(result_data)
                                if query_result_text:
                                    parts.append(query_result_text)
                                
                    except Exception as e:
                        logger.error(f"Error fetching query result: {str(e)}")
        
        if parts:
            return "\n\n".join(parts)
        
        # Fallback if no parts extracted
        logger.warning("No content extracted from message")
        return "Sorry, I couldn't extract Genie's response. Please try again."
    
    def _format_query_result(self, result_data: Dict[str, Any]) -> str:
        """Format query result data into readable text"""
        try:
            # Check for statement_response with data
            if "statement_response" in result_data:
                stmt = result_data["statement_response"]
                
                # Get column names from manifest.schema.columns
                columns = []
                if "manifest" in stmt and "schema" in stmt["manifest"]:
                    manifest_schema = stmt["manifest"]["schema"]
                    if "columns" in manifest_schema and manifest_schema["columns"]:
                        columns = [col.get("name", f"col{i}") for i, col in enumerate(manifest_schema["columns"])]
                
                # Get data from result.data_array
                if "result" in stmt and stmt["result"]:
                    result = stmt["result"]
                    
                    # Format as table if we have data_array
                    if "data_array" in result and result["data_array"]:
                        rows = result["data_array"]
                        
                        if not rows:
                            return ""
                        
                        # Fallback if no columns from manifest
                        if not columns:
                            columns = [f"Column {i+1}" for i in range(len(rows[0]))]
                        
                        # Calculate column widths for better formatting
                        col_widths = [len(str(col)) for col in columns]
                        for row in rows[:10]:
                            for i, val in enumerate(row):
                                if i < len(col_widths):
                                    col_widths[i] = max(col_widths[i], len(str(val)) if val is not None else 4)
                        
                        # Build formatted table
                        output_lines = ["\n```"]  # Use code block for monospace formatting
                        
                        # Header row
                        header = " | ".join(str(col).ljust(col_widths[i]) for i, col in enumerate(columns))
                        output_lines.append(header)
                        
                        # Separator line
                        separator = "-+-".join("-" * width for width in col_widths)
                        output_lines.append(separator)
                        
                        # Data rows
                        for row in rows[:10]:
                            formatted_row = []
                            for i, val in enumerate(row):
                                str_val = str(val) if val is not None else "NULL"
                                if i < len(col_widths):
                                    formatted_row.append(str_val.ljust(col_widths[i]))
                            output_lines.append(" | ".join(formatted_row))
                        
                        output_lines.append("```")
                        
                        if len(rows) > 10:
                            output_lines.append(f"\n({len(rows) - 10} more rows...)")
                        
                        return "\n".join(output_lines)
            
            return ""
            
        except Exception as e:
            logger.error(f"Error formatting query result: {str(e)}", exc_info=True)
            return ""
    
    def _extract_response_text(self, response: Dict[str, Any]) -> str:
        """
        Extract text from Genie API response.
        Only returns explanations and query results, not the user's question or SQL queries.
        """
        try:
            parts = []
            
            # Check attachments (where Genie's responses typically are)
            if "attachments" in response and response["attachments"]:
                logger.info(f"Found {len(response['attachments'])} attachments")
                for i, attachment in enumerate(response["attachments"]):
                    if not isinstance(attachment, dict):
                        continue
                    
                    logger.info(f"Attachment {i} keys: {list(attachment.keys())}")
                    
                    # Try multiple ways to extract text content
                    text_content = None
                    
                    # Method 1: attachment.text.content (most common)
                    if "text" in attachment and attachment["text"]:
                        if isinstance(attachment["text"], dict):
                            text_content = attachment["text"].get("content", "")
                        else:
                            text_content = str(attachment["text"])
                    
                    # Method 2: attachment.content directly
                    if not text_content and "content" in attachment:
                        text_content = str(attachment["content"])
                    
                    # Method 3: attachment.description
                    if not text_content and "description" in attachment:
                        text_content = str(attachment["description"])
                    
                    if text_content:
                        logger.info(f"Extracted text from attachment {i}: {text_content[:100]}...")
                        parts.append(text_content)
            
            # Try getting content from various top-level fields
            if not parts:
                logger.info("No content from attachments, trying other fields...")
                
                for field in ["content", "text", "description", "message", "response", "result"]:
                    if field in response and response[field]:
                        value = response[field]
                        if isinstance(value, dict):
                            # Try to get nested content
                            if "content" in value:
                                parts.append(str(value["content"]))
                            elif "text" in value:
                                parts.append(str(value["text"]))
                        elif isinstance(value, str) and len(value) > 20:
                            parts.append(value)
            
            if parts:
                result = "\n\n".join(parts)
                logger.info(f"Successfully extracted {len(parts)} parts, total length: {len(result)}")
                return result
            
            # Still nothing found - return full response as JSON for debugging
            logger.error("Could not extract any content from response!")
            return f"⚠️ Debug - Full response:\n```json\n{json.dumps(response, indent=2)[:2000]}\n```"
            
        except Exception as e:
            logger.error(f"Error extracting response: {str(e)}", exc_info=True)
            return f"Error formatting response: {str(e)}"
