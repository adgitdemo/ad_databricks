"""
Microsoft Teams Bot Handler
Processes messages from Teams and communicates with Genie
"""
import logging
import json
import re
from typing import Dict, Any
from botbuilder.core import TurnContext, BotFrameworkAdapter, BotFrameworkAdapterSettings, MessageFactory, CardFactory
from botbuilder.schema import Activity, ActivityTypes, HeroCard, CardAction, ActionTypes

logger = logging.getLogger(__name__)


class TeamsBot:
    """Microsoft Teams Bot that integrates with Databricks Genie"""
    
    def __init__(self, app_id: str, app_password: str, genie_client, app_tenant_id: str = None):
        """
        Initialize Teams Bot
        
        Args:
            app_id: Microsoft App ID
            app_password: Microsoft App Password
            genie_client: Initialized Genie client
            app_tenant_id: Microsoft App Tenant ID (for SingleTenant apps)
        """
        self.app_id = app_id or ""
        self.app_password = app_password or ""
        self.app_tenant_id = app_tenant_id or ""
        self.genie_client = genie_client
        
        # Initialize Bot Framework Adapter with tenant ID for SingleTenant authentication
        settings = BotFrameworkAdapterSettings(
            app_id=self.app_id,
            app_password=self.app_password,
            channel_auth_tenant=self.app_tenant_id if self.app_tenant_id else None,
            auth_configuration=None  # Use default authentication
        )
        self.adapter = BotFrameworkAdapter(settings)
        
        # Disable credential validation for development/testing
        # This helps with SingleTenant authentication issues
        self.adapter.settings.app_id = self.app_id
        self.adapter.settings.app_password = self.app_password
        
        # Store conversation contexts (in production, use persistent storage)
        self.conversations: Dict[str, str] = {}
        
        # Set up error handler
        async def on_error(context: TurnContext, error: Exception):
            logger.error(f"Error in bot: {str(error)}", exc_info=True)
            try:
                await context.send_activity("Sorry, something went wrong. Please try again.")
            except Exception as e:
                logger.error(f"Failed to send error message: {str(e)}")
        
        self.adapter.on_turn_error = on_error
        
        logger.info(f"Teams Bot initialized with App ID: {self.app_id[:10]}... (Tenant: {self.app_tenant_id[:10] if self.app_tenant_id else 'None'}...)")
    
    async def handle_request(self, req_body: dict, auth_header: str) -> Dict[str, Any]:
        """
        Handle incoming HTTP request from Teams
        
        Args:
            req_body: Request body with activity
            auth_header: Authorization header
            
        Returns:
            Response dictionary
        """
        try:
            # Create activity from request
            activity = Activity().deserialize(req_body)
            
            logger.info(f"Received activity type: {activity.type}, from: {activity.from_property.name if activity.from_property else 'unknown'}")
            
            # Process the activity through the adapter
            async def bot_logic(turn_context: TurnContext):
                try:
                    await self._on_turn(turn_context)
                except Exception as e:
                    logger.error(f"Error in bot_logic: {str(e)}", exc_info=True)
                    try:
                        await turn_context.send_activity("Sorry, I encountered an error processing your message.")
                    except:
                        pass
            
            # Process activity with error handling for authentication issues
            try:
                await self.adapter.process_activity(activity, auth_header, bot_logic)
            except KeyError as e:
                if 'access_token' in str(e):
                    logger.error("Bot Framework authentication failed - credentials may be invalid")
                    # Try to process without full authentication for Web Chat testing
                    if activity.channel_id == 'emulator' or activity.channel_id == 'webchat':
                        logger.info("Attempting to process message without full authentication for testing")
                        await bot_logic(TurnContext(self.adapter, activity))
                    else:
                        raise
                else:
                    raise
            
            return {
                "status": "ok",
                "message": "Activity processed"
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error handling request: {error_msg}", exc_info=True)
            
            # Check for specific authentication errors
            if 'access_token' in error_msg or 'KeyError' in error_msg:
                return {
                    "status": "error",
                    "error": "Bot authentication failed. Please verify your MICROSOFT_APP_ID and MICROSOFT_APP_PASSWORD are correct.",
                    "details": error_msg
                }
            
            return {
                "status": "error",
                "error": error_msg
            }
    
    async def _on_turn(self, turn_context: TurnContext):
        """
        Handle incoming turn
        
        Args:
            turn_context: Turn context from Bot Framework
        """
        try:
            if not turn_context or not turn_context.activity:
                logger.error("Turn context or activity is None")
                return
            
            activity_type = turn_context.activity.type
            logger.info(f"Processing activity type: {activity_type}")
            
            if activity_type == ActivityTypes.message:
                await self._on_message_activity(turn_context)
            elif activity_type == ActivityTypes.conversation_update:
                await self._on_conversation_update(turn_context)
            else:
                logger.info(f"Unhandled activity type: {activity_type}")
                
        except Exception as e:
            logger.error(f"Error in _on_turn: {str(e)}", exc_info=True)
            try:
                await turn_context.send_activity("Sorry, I encountered an error. Please try again.")
            except:
                pass
    
    async def _on_conversation_update(self, turn_context: TurnContext):
        """Handle conversation update events (like bot being added to conversation)"""
        try:
            if turn_context.activity.members_added:
                for member in turn_context.activity.members_added:
                    if member.id != turn_context.activity.recipient.id:
                        await turn_context.send_activity(
                            "Hello! I'm your Databricks Genie assistant. "
                            "Ask me questions about your data, and I'll help you find insights!"
                        )
        except Exception as e:
            logger.error(f"Error in conversation update: {str(e)}")
    
    def _extract_user_message(self, turn_context: TurnContext) -> str:
        """Return the user's text with any bot mention markup removed."""
        activity = turn_context.activity
        if not activity or not activity.text:
            return ""

        message = activity.text
        mention_texts = []
        mention_names = []

        try:
            if activity.entities:
                for entity in activity.entities:
                    if entity.get('type') == 'mention':
                        mention_text = entity.get('text') or ''
                        if mention_text:
                            mention_texts.append(mention_text)
                        mentioned = entity.get('mentioned', {})
                        name = mentioned.get('name') or ''
                        if name:
                            mention_names.append(name)
        except Exception as mention_error:
            logger.debug(f"Failed to collect mention info: {mention_error}")

        # Remove markup like <at>Bot Name</at> directly
        for mention_text in mention_texts:
            message = message.replace(mention_text, ' ')
        #message = message.replace('<at>', ' ').replace('</at>', ' ')
        message = message.replace('<at>Databricks Genie</at>', '')

        # Remove plain bot names (with or without @) at start of message
        possible_names = set(mention_names)
        recipient_name = getattr(getattr(activity, 'recipient', None), 'name', '') or ''
        if recipient_name:
            possible_names.add(recipient_name)

        for name in possible_names:
            if not name:
                continue
            pattern = rf'^\s*@?{re.escape(name)}\b[:,-]*'
            message = re.sub(pattern, ' ', message, flags=re.IGNORECASE)

        return message.strip()

    async def _on_message_activity(self, turn_context: TurnContext):
        """
        Handle incoming message activity
        
        Args:
            turn_context: Turn context from Bot Framework
        """
        try:
            # Validate turn context and activity
            if not turn_context or not turn_context.activity:
                logger.error("Turn context or activity is None")
                return
            
            # Check if this is a feedback button click
            if turn_context.activity.value:
                try:
                    feedback_data = turn_context.activity.value if isinstance(turn_context.activity.value, dict) else json.loads(turn_context.activity.value)
                    if feedback_data.get("action") == "feedback":
                        await self._handle_feedback(turn_context, feedback_data)
                        return
                except:
                    pass  # Not feedback data, continue as normal message
            
            # Get the user's message and strip bot mentions
            user_message = self._extract_user_message(turn_context)
            if not user_message:
                logger.warning("Empty message received")
                await turn_context.send_activity("Please send me a question about your data.")
                return
            
            # Get conversation ID
            conversation_id = "default"
            if turn_context.activity.conversation and turn_context.activity.conversation.id:
                conversation_id = turn_context.activity.conversation.id
            
            logger.info(f"Processing message from {conversation_id}: {user_message[:100]}")
            
            # Send typing indicator
            try:
                await turn_context.send_activity(Activity(type=ActivityTypes.typing))
            except Exception as e:
                logger.warning(f"Failed to send typing indicator: {str(e)}")
            
            # Check if this is a continuing conversation with Genie
            genie_conversation_id = self.conversations.get(conversation_id)
            
            if genie_conversation_id:
                # Continue existing conversation
                logger.info(f"Continuing Genie conversation: {genie_conversation_id}")
                result = await self.genie_client.continue_conversation(
                    genie_conversation_id, 
                    user_message
                )
            else:
                # Start new conversation
                logger.info("Starting new Genie conversation")
                result = await self.genie_client.ask_question(user_message)
                
                # Store conversation ID for follow-up questions
                if result and result.get("conversation_id"):
                    self.conversations[conversation_id] = result["conversation_id"]
                    logger.info(f"Stored Genie conversation ID: {result['conversation_id']}")
            
            # Send the response back to the user
            if not result:
                await turn_context.send_activity("Sorry, I didn't get a response. Please try again.")
                return
                
            if result.get("status") == "success":
                response_text = result.get("response", "I received your question but got no response.")
                genie_conversation_id = result.get("conversation_id")
                genie_message_id = result.get("message_id")
                
                # Send response with interactive feedback buttons
                try:
                    await self._send_response_with_feedback(
                        turn_context,
                        response_text,
                        genie_conversation_id,
                        genie_message_id
                    )
                    logger.info(f"Sent response to user: {response_text[:100]}...")
                except Exception as feedback_error:
                    logger.error(
                        f"Error sending response with feedback: {feedback_error}",
                        exc_info=True
                    )
                    try:
                        await turn_context.send_activity(response_text)
                    except Exception as send_error:
                        logger.error(f"Error sending fallback response: {send_error}")
                        await turn_context.send_activity(f"Response: {response_text}")
            else:
                error_message = result.get("error", "Unknown error")
                await turn_context.send_activity(
                    f"Sorry, I encountered an error: {error_message}\n\n"
                    "Please make sure your Databricks Genie Space is properly configured."
                )
                logger.error(f"Error from Genie: {error_message}")
            
        except Exception as e:
            logger.error(f"Error in message activity: {str(e)}", exc_info=True)
            try:
                await turn_context.send_activity(
                    "Sorry, I encountered an unexpected error. Please try again."
                )
            except:
                pass
    
    async def _send_response_with_feedback(self, turn_context: TurnContext, response_text: str, conversation_id: str, message_id: str):
        """Send response with feedback buttons"""
        try:
            # Send the text response first
            await turn_context.send_activity(response_text)
            
            # Only add feedback buttons if we have valid IDs
            if not conversation_id or not message_id:
                return
            
            # Create feedback card with thumbs up/down buttons
            feedback_card = HeroCard(
                text="Was this response helpful?",
                buttons=[
                    CardAction(
                        type=ActionTypes.message_back,
                        title="👍 Yes",
                        value=json.dumps({"action": "feedback", "rating": "positive", "conversation_id": conversation_id, "message_id": message_id}),
                        text="Thanks for the feedback!",
                        display_text="👍"
                    ),
                    CardAction(
                        type=ActionTypes.message_back,
                        title="👎 No",
                        value=json.dumps({"action": "feedback", "rating": "negative", "conversation_id": conversation_id, "message_id": message_id}),
                        text="Thanks for the feedback!",
                        display_text="👎"
                    )
                ]
            )
            
            message = MessageFactory.attachment(CardFactory.hero_card(feedback_card))
            await turn_context.send_activity(message)
            
        except Exception as e:
            logger.error(f"Error sending feedback card: {str(e)}", exc_info=True)
            # Don't fail the whole response if feedback card fails
    
    async def _handle_feedback(self, turn_context: TurnContext, feedback_data: Dict[str, Any]):
        """Handle feedback button click"""
        try:
            rating = feedback_data.get("rating")
            conversation_id = feedback_data.get("conversation_id")
            message_id = feedback_data.get("message_id")
            
            if not all([rating, conversation_id, message_id]):
                logger.warning("Invalid feedback data - missing fields")
                await turn_context.send_activity("Sorry, couldn't record your feedback.")
                return
            
            # Send feedback to Genie
            result = await self.genie_client.send_feedback(conversation_id, message_id, rating)
            
            if result.get("status") == "success":
                logger.info(f"Feedback ({rating}) recorded in Genie")
                await turn_context.send_activity("Thanks for your feedback!")
            else:
                logger.error(f"Failed to send feedback: {result.get('error')}")
                await turn_context.send_activity("Sorry, couldn't record feedback.")
                
        except Exception as e:
            logger.error(f"Error handling feedback: {str(e)}")
            await turn_context.send_activity("Sorry, an error occurred while recording feedback.")
