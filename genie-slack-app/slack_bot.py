"""
Slack bot handler for Databricks Genie integration
"""
import logging
from typing import Dict, Any
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from databricks_genie_client import DatabricksGenieClient

logger = logging.getLogger(__name__)


class SlackGenieBot:
    """Slack bot that interfaces with Databricks Genie"""
    
    def __init__(
        self, 
        slack_bot_token: str,
        slack_signing_secret: str,
        slack_app_token: str,
        genie_client: DatabricksGenieClient
    ):
        """
        Initialize the Slack bot
        
        Args:
            slack_bot_token: Slack bot token
            slack_signing_secret: Slack signing secret
            slack_app_token: Slack app token for socket mode
            genie_client: Databricks Genie client instance
        """
        self.app = App(
            token=slack_bot_token,
            signing_secret=slack_signing_secret
        )
        self.slack_app_token = slack_app_token
        self.genie_client = genie_client
        self.client = WebClient(token=slack_bot_token)
        
        # Store conversation mappings: slack_thread_ts -> databricks_conversation_id
        self.conversation_map: Dict[str, str] = {}
        
        # Store message mappings for feedback: message_ts -> (conversation_id, message_id)
        self.message_feedback_map: Dict[str, tuple] = {}
        
        # Register event handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register Slack event handlers"""
        
        @self.app.event("app_mention")
        def handle_app_mention(event, say, client):
            """Handle when the bot is mentioned"""
            self._handle_message(event, say, client)
        
        @self.app.event("message")
        def handle_message_events(event, say, client):
            """Handle direct messages to the bot"""
            # Only handle DMs and threaded replies
            if event.get("channel_type") == "im" or event.get("thread_ts"):
                self._handle_message(event, say, client)
        
        @self.app.action("feedback_positive")
        def handle_positive_feedback(ack, body, client):
            """Handle positive feedback button click"""
            ack()
            self._handle_feedback(body, "positive", client)
        
        @self.app.action("feedback_negative")
        def handle_negative_feedback(ack, body, client):
            """Handle negative feedback button click"""
            ack()
            self._handle_feedback(body, "negative", client)
    
    def _handle_message(self, event: Dict[str, Any], say, client):
        """
        Handle incoming messages from Slack
        
        Args:
            event: Slack event data
            say: Slack say function
            client: Slack client
        """
        try:
            # Extract message details
            text = event.get("text", "")
            user = event.get("user")
            channel = event.get("channel")
            thread_ts = event.get("thread_ts") or event.get("ts")
            
            # Ignore bot messages
            if event.get("bot_id"):
                return
            
            # Remove bot mention from text
            text = self._clean_message_text(text)
            
            if not text.strip():
                say("Please ask me a question about your data!", thread_ts=thread_ts)
                return
            
            # Send typing indicator
            client.chat_postMessage(
                channel=channel,
                text="🤔 Thinking...",
                thread_ts=thread_ts
            )
            
            # Get or create Databricks conversation
            conversation_id = self.conversation_map.get(thread_ts)
            
            # Ask Genie
            logger.info(f"Asking Genie: {text}")
            result = self.genie_client.ask_question(text, conversation_id)
            
            # Store conversation mapping for thread continuity
            if result.get("conversation_id"):
                self.conversation_map[thread_ts] = result["conversation_id"]
            
            # Format and send response
            response_text = self._format_response(result)
            
            # Send the response (without feedback buttons)
            say(response_text, thread_ts=thread_ts)
            
            # Send query result data if available
            result_data = result.get("result_data")
            if result_data:
                data = result_data.get("data", {})
                if data.get("data_array"):
                    self._send_query_results(channel, thread_ts, result_data, client)
            
            # Send any attachments (charts, tables, etc.)
            attachments = result.get("attachments", [])
            if attachments:
                self._send_attachments(channel, thread_ts, attachments, client)
            
            # Send suggested follow-up questions if available
            suggested_questions = result.get("suggested_questions", [])
            if suggested_questions:
                self._send_suggested_questions(channel, thread_ts, suggested_questions, client)
            
            # Send feedback buttons as the last message
            if result.get("success"):
                conversation_id = result.get("conversation_id")
                message_id = result.get("message_id")
                logger.info(f"Preparing feedback buttons - conv_id: {conversation_id}, msg_id: {message_id}")
                
                if conversation_id and message_id:
                    feedback_msg = self._send_feedback_buttons(channel, thread_ts, client)
                    # Store message mapping for feedback
                    if feedback_msg:
                        msg_ts = feedback_msg.get("ts")
                        logger.info(f"Feedback message sent with ts: {msg_ts}")
                        if msg_ts:
                            self.message_feedback_map[msg_ts] = (conversation_id, message_id)
                            logger.info(f"Stored feedback mapping: {msg_ts} -> ({conversation_id}, {message_id})")
                    else:
                        logger.error("Failed to send feedback buttons message")
                else:
                    logger.warning(f"Missing conversation_id or message_id - cannot create feedback buttons")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            say(f"Sorry, I encountered an error: {str(e)}", thread_ts=thread_ts)
    
    def _clean_message_text(self, text: str) -> str:
        """
        Remove bot mention and clean up message text
        
        Args:
            text: Raw message text
            
        Returns:
            Cleaned text
        """
        # Remove bot mentions like <@U123456>
        import re
        text = re.sub(r'<@[A-Z0-9]+>', '', text)
        return text.strip()
    
    def _format_response(self, result: Dict[str, Any]) -> str:
        """
        Format the Genie response for Slack
        
        Args:
            result: Result dict from Genie client
            
        Returns:
            Formatted message text
        """
        if not result.get("success"):
            error = result.get("error", "Unknown error")
            return f"❌ {error}"
        
        response = result.get("response", "")
        
        # Don't show row count per user request - actual data will be shown separately
        
        return response if response else "✅ Query executed successfully"
    
    def _send_attachments(
        self, 
        channel: str, 
        thread_ts: str, 
        attachments: list, 
        client
    ):
        """
        Send attachments (charts, files) to Slack
        
        Args:
            channel: Slack channel ID
            thread_ts: Thread timestamp
            attachments: List of attachment dicts
            client: Slack client
        """
        for attachment in attachments:
            try:
                attachment_type = attachment.get("type")
                
                if attachment_type == "chart":
                    # Send chart info
                    chart_url = attachment.get("url")
                    chart_title = attachment.get("title", "Chart")
                    
                    if chart_url:
                        client.chat_postMessage(
                            channel=channel,
                            text=f"📊 *{chart_title}*\n{chart_url}",
                            thread_ts=thread_ts
                        )
                
                elif attachment_type == "table":
                    # Format table data
                    table_data = attachment.get("data", [])
                    if table_data:
                        table_text = self._format_table(table_data)
                        client.chat_postMessage(
                            channel=channel,
                            text=f"```{table_text}```",
                            thread_ts=thread_ts
                        )
                        
            except Exception as e:
                logger.error(f"Error sending attachment: {e}")
    
    def _send_query_results(self, channel: str, thread_ts: str, result_data: dict, client):
        """
        Send formatted query results to Slack
        
        Args:
            channel: Slack channel ID
            thread_ts: Thread timestamp
            result_data: Query result data from statement API
            client: Slack client
        """
        try:
            data = result_data.get("data", {})
            schema = result_data.get("schema", {})
            
            data_array = data.get("data_array", [])
            row_count = data.get("row_count", len(data_array))
            
            if not data_array:
                return
            
            # Get column names from schema
            columns = schema.get("columns", [])
            column_names = [col.get("name", f"col_{i}") for i, col in enumerate(columns)]
            
            # Format as table (limit to first 10 rows for readability)
            max_rows = 10
            table_text = self._format_data_array(column_names, data_array[:max_rows])
            
            # Build message
            result_message = f"*Query Results:*\n```\n{table_text}\n```"
            
            if row_count > max_rows:
                result_message += f"\n_Showing {max_rows} of {row_count} rows_"
            
            client.chat_postMessage(
                channel=channel,
                text=result_message,
                thread_ts=thread_ts
            )
            
        except Exception as e:
            logger.error(f"Error sending query results: {e}")
    
    def _send_suggested_questions(self, channel: str, thread_ts: str, suggested_questions: list, client):
        """
        Send suggested follow-up questions to Slack
        
        Args:
            channel: Slack channel ID
            thread_ts: Thread timestamp
            suggested_questions: List of suggested question strings
            client: Slack client
        """
        try:
            if not suggested_questions:
                return
            
            # Format suggested questions with numbered list
            questions_text = "*💡 Suggested follow-up questions:*\n"
            for i, question in enumerate(suggested_questions, 1):
                questions_text += f"{i}. {question}\n"
            
            client.chat_postMessage(
                channel=channel,
                text=questions_text,
                thread_ts=thread_ts
            )
            
        except Exception as e:
            logger.error(f"Error sending suggested questions: {e}")
    
    def _send_feedback_buttons(self, channel: str, thread_ts: str, client):
        """
        Send feedback buttons as a separate message to Slack
        
        Args:
            channel: Slack channel ID
            thread_ts: Thread timestamp
            client: Slack client
            
        Returns:
            Response from Slack API
        """
        try:
            # Create blocks with just feedback buttons
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Was this response helpful?*"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "👍 Helpful",
                                "emoji": True
                            },
                            "action_id": "feedback_positive"
                        },
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "👎 Not Helpful",
                                "emoji": True
                            },
                            "action_id": "feedback_negative"
                        }
                    ]
                }
            ]
            
            response = client.chat_postMessage(
                channel=channel,
                blocks=blocks,
                text="Was this response helpful?",  # Fallback text for notifications
                thread_ts=thread_ts
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error sending feedback buttons: {e}")
            return None
    
    def _handle_feedback(self, body: Dict[str, Any], rating: str, client):
        """
        Handle feedback button click
        
        Args:
            body: Slack action body
            rating: Feedback rating ("positive" or "negative")
            client: Slack client
        """
        try:
            # Extract message info
            message = body.get("message", {})
            msg_ts = message.get("ts")
            channel = body.get("channel", {}).get("id")
            user = body.get("user", {}).get("id")
            
            logger.info(f"Feedback button clicked: {rating}, msg_ts: {msg_ts}")
            logger.info(f"Available feedback mappings: {list(self.message_feedback_map.keys())}")
            
            # Get conversation_id and message_id from stored mapping
            feedback_info = self.message_feedback_map.get(msg_ts)
            
            if not feedback_info:
                logger.warning(f"No feedback info found for message {msg_ts}")
                logger.warning(f"Body: {body}")
                
                # Send error message to user
                error_blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "⚠️ _Unable to submit feedback. Please try asking a new question._"
                        }
                    }
                ]
                
                client.chat_update(
                    channel=channel,
                    ts=msg_ts,
                    blocks=error_blocks,
                    text="Unable to submit feedback"
                )
                return
            
            conversation_id, message_id = feedback_info
            logger.info(f"Sending feedback for conversation {conversation_id}, message {message_id}")
            
            # Send feedback to Databricks Genie
            success = self.genie_client.send_message_feedback(
                conversation_id=conversation_id,
                message_id=message_id,
                rating=rating
            )
            
            if success:
                # Update the message to show feedback was recorded
                emoji = "👍" if rating == "positive" else "👎"
                feedback_text = f"{emoji} _Thanks for your feedback!_"
                
                # Replace the feedback question with confirmation
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": feedback_text
                        }
                    }
                ]
                
                client.chat_update(
                    channel=channel,
                    ts=msg_ts,
                    blocks=blocks,
                    text=feedback_text
                )
                
                logger.info(f"User {user} gave {rating} feedback for message {message_id}")
            else:
                logger.error(f"Failed to send feedback to Genie API")
                
                # Show error to user
                error_blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "❌ _Failed to submit feedback. Please try again._"
                        }
                    }
                ]
                
                client.chat_update(
                    channel=channel,
                    ts=msg_ts,
                    blocks=error_blocks,
                    text="Failed to submit feedback"
                )
                
        except Exception as e:
            logger.error(f"Error handling feedback: {e}", exc_info=True)
    
    def _format_data_array(self, column_names: list, data_array: list) -> str:
        """
        Format data array for display in Slack with improved formatting
        
        Args:
            column_names: List of column names
            data_array: List of row arrays
            
        Returns:
            Formatted table string
        """
        if not data_array:
            return "No data"
        
        # Calculate column widths (consider both headers and data)
        col_widths = []
        col_types = []  # Track if column appears to be numeric for alignment
        
        for i in range(len(column_names)):
            max_width = len(column_names[i])
            is_numeric = True
            
            if data_array:
                for row in data_array:
                    val_str = str(row[i]) if row[i] is not None else ""
                    max_width = max(max_width, len(val_str))
                    # Check if value is numeric
                    if row[i] is not None and not self._is_numeric(row[i]):
                        is_numeric = False
            
            col_widths.append(min(max_width + 2, 30))  # Cap at 30 chars, add padding
            col_types.append(is_numeric)
        
        # Create table with headers
        lines = []
        
        # Add header row (centered)
        header_parts = []
        for name, width in zip(column_names, col_widths):
            truncated = name[:width].strip()
            header_parts.append(truncated.center(width))
        lines.append("│".join(header_parts))
        
        # Add separator with proper formatting
        separator_parts = []
        for width in col_widths:
            separator_parts.append("─" * width)
        lines.append("┼".join(separator_parts))
        
        # Add data rows with proper alignment
        for row in data_array:
            row_parts = []
            for val, width, is_numeric in zip(row, col_widths, col_types):
                val_str = str(val) if val is not None else ""
                truncated = val_str[:width].strip()
                
                # Right-align numbers, left-align text
                if is_numeric and self._is_numeric(val):
                    formatted = truncated.rjust(width)
                else:
                    formatted = truncated.ljust(width)
                
                row_parts.append(formatted)
            lines.append("│".join(row_parts))
        
        return "\n".join(lines)
    
    def _is_numeric(self, value) -> bool:
        """Check if a value is numeric"""
        if value is None:
            return False
        try:
            float(str(value))
            return True
        except (ValueError, TypeError):
            return False
    
    def _format_table(self, data: list, max_rows: int = 10) -> str:
        """
        Format table data for display in Slack
        
        Args:
            data: List of row dicts
            max_rows: Maximum number of rows to display
            
        Returns:
            Formatted table string
        """
        if not data:
            return "No data"
        
        # Get headers
        headers = list(data[0].keys())
        
        # Create table
        lines = []
        lines.append(" | ".join(headers))
        lines.append("-" * len(lines[0]))
        
        for row in data[:max_rows]:
            lines.append(" | ".join(str(row.get(h, "")) for h in headers))
        
        if len(data) > max_rows:
            lines.append(f"... and {len(data) - max_rows} more rows")
        
        return "\n".join(lines)
    
    def start(self):
        """Start the Slack bot in socket mode"""
        handler = SocketModeHandler(self.app, self.slack_app_token)
        logger.info("Starting Slack bot in socket mode...")
        handler.start()

