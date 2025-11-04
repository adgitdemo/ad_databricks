"""
Azure Functions Entry Point
Handles HTTP requests from Microsoft Teams Bot Service
"""
import azure.functions as func
import logging
import json

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Function App
app = func.FunctionApp()

# Lazy initialization
_bot = None
_genie = None


def get_bot():
    """Lazy initialization of bot and genie client"""
    global _bot, _genie
    
    if _bot is None:
        try:
            from config import Config
            from databricks.genie_client import GenieClient
            from bot.teams_bot import TeamsBot
            
            # Validate config
            Config.validate()
            config = Config()
            
            # Initialize Genie Client
            _genie = GenieClient(
                host=config.DATABRICKS_HOST,
                client_id=config.DATABRICKS_CLIENT_ID,
                client_secret=config.DATABRICKS_CLIENT_SECRET,
                tenant_id=config.DATABRICKS_TENANT_ID,
                space_id=config.DATABRICKS_GENIE_SPACE_ID
            )
            
            # Initialize Teams Bot
            _bot = TeamsBot(
                app_id=config.MICROSOFT_APP_ID,
                app_password=config.MICROSOFT_APP_PASSWORD,
                genie_client=_genie,
                app_tenant_id=config.MICROSOFT_APP_TENANT_ID
            )
            
            logger.info("Bot and Genie client initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing bot: {str(e)}")
            raise
    
    return _bot


@app.route(route="messages", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
async def messages(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle incoming messages from Microsoft Teams
    This is the webhook endpoint that Teams calls
    """
    logger.info("=== Messages endpoint called ===")
    
    try:
        # Get bot instance
        bot = get_bot()
        
        # Get request body
        req_body = req.get_json()
        logger.info(f"Request body: {json.dumps(req_body, indent=2)}")
        
        # Get authorization header
        auth_header = req.headers.get("Authorization", "")
        
        # Process the message through the bot
        result = await bot.handle_request(req_body, auth_header)
        
        logger.info(f"Bot result: {result}")
        
        # Return success
        return func.HttpResponse(
            json.dumps({"status": "ok", "result": result}),
            mimetype="application/json",
            status_code=200
        )
        
    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": "Invalid request", "details": str(e)}),
            mimetype="application/json",
            status_code=400
        )
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Internal server error", "details": str(e)}),
            mimetype="application/json",
            status_code=500
        )


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint"""
    logger.info("Health check requested")
    
    return func.HttpResponse(
        json.dumps({
            "status": "healthy",
            "service": "Databricks Genie Teams Bot"
        }),
        mimetype="application/json",
        status_code=200
    )


@app.route(route="", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
async def root(req: func.HttpRequest) -> func.HttpResponse:
    """Root endpoint - shows status"""
    logger.info("Root endpoint accessed")
    
    try:
        from config import Config
        config = Config()
        host = config.DATABRICKS_HOST
        space_id = config.DATABRICKS_GENIE_SPACE_ID
        app_id = config.MICROSOFT_APP_ID
        log_level = config.LOG_LEVEL
    except:
        host = "Not configured"
        space_id = "Not configured"
        app_id = "Not configured"
        log_level = "INFO"
    
    status_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Databricks Genie Teams Bot</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #FF3621; }}
            .status {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            .config {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
            .endpoint {{ background: #fff3e0; padding: 10px; border-radius: 5px; margin: 10px 0; }}
            code {{ background: #263238; color: #aed581; padding: 2px 6px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <h1>🤖 Databricks Genie Teams Bot</h1>
        
        <div class="status">
            <h2>✅ Status: Running</h2>
            <p>The bot is ready to receive messages from Microsoft Teams</p>
        </div>
        
        <div class="config">
            <h2>⚙️ Configuration</h2>
            <p><strong>Databricks Host:</strong> {host}</p>
            <p><strong>Genie Space ID:</strong> {space_id}</p>
            <p><strong>Microsoft App ID:</strong> {app_id}</p>
            <p><strong>Log Level:</strong> {log_level}</p>
        </div>
        
        <div class="endpoint">
            <h2>📡 Endpoints</h2>
            <p><strong>Messages:</strong> <code>POST /api/messages</code> - Teams webhook</p>
            <p><strong>Health:</strong> <code>GET /api/health</code> - Health check</p>
            <p><strong>Status:</strong> <code>GET /</code> - This page</p>
        </div>
        
        <div class="status">
            <h2>🔗 Integration</h2>
            <p>Configure your Azure Bot Service messaging endpoint to:</p>
            <code>https://db-genie-teams-bot.azurewebsites.net/api/messages</code>
        </div>
    </body>
    </html>
    """
    
    return func.HttpResponse(
        status_html,
        mimetype="text/html",
        status_code=200
    )
