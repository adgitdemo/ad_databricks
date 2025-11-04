#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# Databricks Genie Teams Bot - Installation Script
# ═══════════════════════════════════════════════════════════════
# This script deploys the bot using ONLY Azure CLI commands.
# It creates all resources, configures authentication, and deploys code.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# LOAD CONFIGURATION
# ═══════════════════════════════════════════════════════════════

# Load from .env if exists, otherwise use defaults below
if [ -f ".env" ]; then
    echo "Loading configuration from .env..."
    set -a
    source .env
    set +a
fi

# Default Configuration (used if .env doesn't exist)
DATABRICKS_HOST="${DATABRICKS_HOST:-https://adb-271413217994145.5.azuredatabricks.net}"
DATABRICKS_GENIE_SPACE_ID="${DATABRICKS_GENIE_SPACE_ID:-01f0b8ebb6e01f9a8f75ec08bb1e70ba}"
RESOURCE_GROUP="${RESOURCE_GROUP:-databricks-genie-rg}"
LOCATION="${LOCATION:-eastus}"
NAME_PREFIX="${NAME_PREFIX:-db-genie}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# ═══════════════════════════════════════════════════════════════
# AUTO-GENERATED NAMES (with timestamp for uniqueness)
# ═══════════════════════════════════════════════════════════════

TIMESTAMP=$(date +%Y%m%d%H%M%S)
FUNCTION_APP_NAME="${NAME_PREFIX}-func-${TIMESTAMP}"
BOT_NAME="${NAME_PREFIX}-bot-${TIMESTAMP}"
BOT_DISPLAY_NAME="Databricks Genie Bot ${TIMESTAMP}"
STORAGE_ACCOUNT_RAW="${NAME_PREFIX//-/}${TIMESTAMP}"
STORAGE_ACCOUNT=$(echo "${STORAGE_ACCOUNT_RAW}" | tr '[:upper:]' '[:lower:]' | cut -c1-24)
PACKAGE_FILE="databricks-genie-bot-deploy-linux.zip"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

header() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
}

# ═══════════════════════════════════════════════════════════════
# BANNER
# ═══════════════════════════════════════════════════════════════

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║          🚀 Databricks Genie Teams Bot Deploy 🚀           ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════

if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_GENIE_SPACE_ID" ]; then
  echo -e "${RED}❌ Databricks configuration missing.${NC} Edit the script and set:\n  • DATABRICKS_HOST\n  • DATABRICKS_GENIE_SPACE_ID"
    exit 1
fi

if [ ! -f "$PACKAGE_FILE" ]; then
  echo -e "${RED}❌ Deployment package not found: $PACKAGE_FILE${NC}"
  echo "   Run: ./scripts/create_deployment_linux.sh first."
    exit 1
fi

echo -e "${BLUE}Configuration Summary${NC}"
echo "  Resource Group : $RESOURCE_GROUP"
echo "  Location       : $LOCATION"
echo "  Function App   : $FUNCTION_APP_NAME"
echo "  Bot Service    : $BOT_NAME"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  Databricks     : $DATABRICKS_HOST"
echo "  Genie Space    : $DATABRICKS_GENIE_SPACE_ID"
echo ""

read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# Get subscription ID and tenant ID
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

# ═══════════════════════════════════════════════════════════════
# STEP 1: RESOURCE GROUP
# ═══════════════════════════════════════════════════════════════

header "Step 1/11: Preparing Resource Group"
if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  EXISTING_LOCATION=$(az group show --name "$RESOURCE_GROUP" --query location -o tsv)
  echo -e "${YELLOW}⚠️  Resource group exists in ${EXISTING_LOCATION}. Using existing group.${NC}"
  LOCATION=$EXISTING_LOCATION
else
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
echo -e "${GREEN}✅ Resource group created${NC}"
fi

# ═══════════════════════════════════════════════════════════════
# STEP 2: STORAGE ACCOUNT
# ═══════════════════════════════════════════════════════════════

header "Step 2/11: Creating Storage Account"
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Storage account exists: $STORAGE_ACCOUNT${NC}"
else
az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
  --sku Standard_LRS \
  --output none
  echo -e "${GREEN}✅ Storage account created${NC}"
fi

# ═══════════════════════════════════════════════════════════════
# STEP 3: FUNCTION APP
# ═══════════════════════════════════════════════════════════════

header "Step 3/11: Creating Function App"
if az functionapp show --name "$FUNCTION_APP_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Function App exists: $FUNCTION_APP_NAME${NC}"
else
az functionapp create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$FUNCTION_APP_NAME" \
    --storage-account "$STORAGE_ACCOUNT" \
    --consumption-plan-location "$LOCATION" \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux \
  --output none
echo -e "${GREEN}✅ Function App created${NC}"
fi

# ═══════════════════════════════════════════════════════════════
# STEP 4: APP REGISTRATION
# ═══════════════════════════════════════════════════════════════

header "Step 4/11: Creating App Registration"
APP_ID=$(az ad app create \
  --display-name "$BOT_DISPLAY_NAME" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

if [ -z "$APP_ID" ]; then
    echo -e "${RED}❌ Failed to create App Registration${NC}"
    exit 1
fi

echo -e "${GREEN}✅ App Registration created${NC}"
echo "   App ID: $APP_ID"
echo "   Tenant ID: $TENANT_ID"

# ═══════════════════════════════════════════════════════════════
# STEP 5: SERVICE PRINCIPAL
# ═══════════════════════════════════════════════════════════════

header "Step 5/11: Creating Service Principal"
if ! az ad sp show --id "$APP_ID" &>/dev/null; then
    az ad sp create --id "$APP_ID" --output none
fi
echo -e "${GREEN}✅ Service principal created${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 6: CLIENT SECRET
# ═══════════════════════════════════════════════════════════════

header "Step 6/11: Generating Client Secret"
APP_SECRET=$(az ad app credential reset \
  --id "$APP_ID" \
  --display-name "deploy-${TIMESTAMP}" \
  --query password -o tsv)

echo -e "${GREEN}✅ Client secret generated${NC}"
echo -e "${YELLOW}⚠️  Save this secret securely: $APP_SECRET${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 6.5: AZURE DATABRICKS API PERMISSION
# ═══════════════════════════════════════════════════════════════

header "Step 6.5/11: Adding Azure Databricks API Permission"

DATABRICKS_RESOURCE_ID="2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
USER_IMPERSONATION_ID="d284fb2b-8c8e-4b89-9e81-03a36a477ac3"

az ad app permission add \
  --id "$APP_ID" \
  --api "$DATABRICKS_RESOURCE_ID" \
  --api-permissions "${USER_IMPERSONATION_ID}=Scope" \
  --output none 2>/dev/null || true

az ad app permission grant \
  --id "$APP_ID" \
  --api "$DATABRICKS_RESOURCE_ID" \
  --scope "user_impersonation" \
  --output none 2>/dev/null || echo -e "${YELLOW}Note: Admin consent may need manual approval${NC}"

echo -e "${GREEN}✅ Azure Databricks API permission added${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 7: FUNCTION APP SETTINGS
# ═══════════════════════════════════════════════════════════════

header "Step 7/11: Configuring Function App Settings"
az functionapp config appsettings set \
  --name "$FUNCTION_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --settings \
    DATABRICKS_HOST="$DATABRICKS_HOST" \
    DATABRICKS_GENIE_SPACE_ID="$DATABRICKS_GENIE_SPACE_ID" \
    DATABRICKS_CLIENT_ID="$APP_ID" \
    DATABRICKS_CLIENT_SECRET="$APP_SECRET" \
    DATABRICKS_TENANT_ID="$TENANT_ID" \
    MICROSOFT_APP_ID="$APP_ID" \
    MICROSOFT_APP_PASSWORD="$APP_SECRET" \
    MICROSOFT_APP_TENANT_ID="$TENANT_ID" \
    PYTHON_ISOLATE_WORKER_DEPENDENCIES=1 \
    PYTHON_ENABLE_WORKER_EXTENSIONS=1 \
    FUNCTIONS_WORKER_RUNTIME=python \
    LOG_LEVEL="$LOG_LEVEL" \
  --output none

echo -e "${GREEN}✅ App settings applied${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 8: DEPLOY CODE
# ═══════════════════════════════════════════════════════════════

header "Step 8/11: Deploying Function Code"
az functionapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --src "$PACKAGE_FILE" \
  --output none

echo -e "${GREEN}✅ Code deployed${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 9: BOT SERVICE
# ═══════════════════════════════════════════════════════════════

header "Step 9/11: Creating Azure Bot Service"
FUNCTION_HOST=$(az functionapp show \
  --name "$FUNCTION_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query defaultHostName -o tsv)
MESSAGING_ENDPOINT="https://$FUNCTION_HOST/api/messages"

az bot create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$BOT_NAME" \
  --appid "$APP_ID" \
  --endpoint "$MESSAGING_ENDPOINT" \
  --sku F0 \
  --app-type SingleTenant \
  --tenant-id "$TENANT_ID" \
  --output none

RESOURCE_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.BotService/botServices/$BOT_NAME"
az resource update --ids "$RESOURCE_ID" --set properties.msaAppSecret="$APP_SECRET" --output none

echo -e "${GREEN}✅ Bot service created${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 10: ENABLE TEAMS CHANNEL
# ═══════════════════════════════════════════════════════════════

header "Step 10/11: Enabling Microsoft Teams Channel"
az bot msteams create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$BOT_NAME" \
  --output none

echo -e "${GREEN}✅ Teams channel enabled${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 11: RESTART FUNCTION APP
# ═══════════════════════════════════════════════════════════════

header "Step 11/11: Restarting Function App"
az functionapp restart \
  --name "$FUNCTION_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --output none

echo -e "${GREEN}✅ Function App restarted${NC}"

# ═══════════════════════════════════════════════════════════════
# CREATE TEAMS APP PACKAGE
# ═══════════════════════════════════════════════════════════════

echo ""
echo -e "${BLUE}Creating Teams app package...${NC}"

# Generate bot display name from NAME_PREFIX
if [ "$NAME_PREFIX" = "db-genie" ]; then
    BOT_SHORT_NAME="Databricks Genie"
    BOT_FULL_NAME="Databricks Genie Bot"
    BOT_DESCRIPTION_SHORT="Ask questions about your data using Databricks Genie AI"
    BOT_DESCRIPTION_FULL="Databricks Genie Bot allows you to ask natural language questions about your data. Connect to your Databricks workspace and get instant answers powered by AI."
elif [ "$NAME_PREFIX" = "db-genie-new-bot" ]; then
    BOT_SHORT_NAME="Genie New Bot"
    BOT_FULL_NAME="Databricks Genie New Bot"
    BOT_DESCRIPTION_SHORT="New bot instance for analytics team"
    BOT_DESCRIPTION_FULL="Databricks Genie Bot - New instance for analytics team. Connect to your Databricks workspace and get instant answers powered by AI."
else
    # For custom prefixes, make it readable
    CLEAN_PREFIX=$(echo "$NAME_PREFIX" | sed 's/db-genie/DB Genie/' | sed 's/-/ /g')
    BOT_SHORT_NAME="$CLEAN_PREFIX"
    BOT_FULL_NAME="Databricks Genie $CLEAN_PREFIX"
    BOT_DESCRIPTION_SHORT="Custom bot instance: $CLEAN_PREFIX"
    BOT_DESCRIPTION_FULL="Databricks Genie Bot - Custom instance: $CLEAN_PREFIX. Connect to your Databricks workspace and get instant answers powered by AI."
fi

# Update manifest with new App ID
APP_ID_PREFIX="${APP_ID:0:8}"
TEAMS_PACKAGE="databricks-genie-teams-app-${APP_ID_PREFIX}.zip"

# Update manifest.json
cat > teams-app-package/manifest.json << EOF
{
  "\$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.16/MicrosoftTeams.schema.json",
  "manifestVersion": "1.16",
  "version": "1.0.1",
  "id": "$APP_ID",
  "packageName": "com.databricks.geniebot",
  "developer": {
    "name": "Databricks Genie Bot",
    "websiteUrl": "https://databricks.com",
    "privacyUrl": "https://databricks.com/privacy",
    "termsOfUseUrl": "https://databricks.com/terms"
  },
  "icons": {
    "color": "color.png",
    "outline": "outline.png"
  },
  "name": {
    "short": "$BOT_SHORT_NAME",
    "full": "$BOT_FULL_NAME"
  },
  "description": {
    "short": "$BOT_DESCRIPTION_SHORT",
    "full": "$BOT_DESCRIPTION_FULL"
  },
  "accentColor": "#FF3621",
  "bots": [
    {
      "botId": "$APP_ID",
      "scopes": [
        "personal",
        "team",
        "groupchat"
      ],
      "supportsFiles": false,
      "isNotificationOnly": false,
      "commandLists": [
        {
          "scopes": [
            "personal",
            "team",
            "groupchat"
          ],
          "commands": [
            {
              "title": "hello",
              "description": "Greet the bot"
            },
            {
              "title": "explain data",
              "description": "Ask Genie to explain your dataset"
            },
            {
              "title": "help",
              "description": "Get help using the bot"
            }
          ]
        }
      ]
    }
  ],
  "permissions": [
    "identity",
    "messageTeamMembers"
  ],
  "validDomains": [
    "*.azurewebsites.net",
    "*.databricks.com"
  ]
}
EOF

# Create zip package
cd teams-app-package
zip -q -r "../$TEAMS_PACKAGE" manifest.json color.png outline.png
cd ..

echo -e "${GREEN}✅ Teams app package created: $TEAMS_PACKAGE${NC}"

# ═══════════════════════════════════════════════════════════════
# SAVE CREDENTIALS
# ═══════════════════════════════════════════════════════════════

HEALTH_URL="https://$FUNCTION_HOST/api/health"
CREDS_FILE="docs/deployment-credentials-${TIMESTAMP}.txt"

cat > "$CREDS_FILE" << EOF
╔════════════════════════════════════════════════════════════╗
║       DATABRICKS GENIE TEAMS BOT - DEPLOYMENT INFO        ║
╚════════════════════════════════════════════════════════════╝

Deployment Date: $(date)

AZURE RESOURCES
═══════════════
Resource Group  : $RESOURCE_GROUP
Location        : $LOCATION
Function App    : $FUNCTION_APP_NAME
Bot Service     : $BOT_NAME
Storage Account : $STORAGE_ACCOUNT

APP REGISTRATION / SERVICE PRINCIPAL
════════════════════════════════════
App ID          : $APP_ID
Tenant ID       : $TENANT_ID
Client Secret   : $APP_SECRET

⚠️  SAVE THIS SECRET SECURELY!

ENDPOINTS
═════════
Bot Messaging   : $MESSAGING_ENDPOINT
Health Check    : $HEALTH_URL
Function Portal : https://$FUNCTION_HOST
Teams Package   : $TEAMS_PACKAGE

DATABRICKS CONFIGURATION
════════════════════════
Workspace URL   : $DATABRICKS_HOST
Genie Space ID  : $DATABRICKS_GENIE_SPACE_ID

════════════════════════════════════════════════════════════

NEXT STEPS (MANUAL):

1. Add Service Principal to Databricks
   • Go to: $DATABRICKS_HOST
   • Admin Console → Identity and access → Service principals
   • Click: + Add service principal
   • Enter: $APP_ID
   • Click: Add
   • Enable: Workspace access

2. Grant Genie Space Access
   • Navigate to Genie space: $DATABRICKS_GENIE_SPACE_ID
   • Click: Share
   • Add service principal: $APP_ID
   • Permission: Can use
   • Click: Save

3. Upload Teams App
   • Upload file: $TEAMS_PACKAGE
   • Teams Admin Center or Teams client

4. Test the Bot
   • In Teams, send: hello
   • Try: explain my data

════════════════════════════════════════════════════════════
EOF

echo -e "${GREEN}✅ Credentials saved to: $CREDS_FILE${NC}"

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════

echo ""
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                   DEPLOYMENT COMPLETE!                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}All Azure resources created successfully!${NC}"
echo ""
echo -e "${BLUE}Deployment Summary:${NC}"
echo "  Resource Group : $RESOURCE_GROUP ($LOCATION)"
echo "  Function App   : $FUNCTION_APP_NAME"
echo "  Bot Service    : $BOT_NAME"
echo "  App ID         : $APP_ID"
echo "  Tenant ID      : $TENANT_ID"
echo "  Endpoint       : $MESSAGING_ENDPOINT"
echo "  Health Check   : $HEALTH_URL"
echo "  Teams Package  : $TEAMS_PACKAGE"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Complete the manual steps in $CREDS_FILE${NC}"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Add service principal to Databricks (App ID: $APP_ID)"
echo "  2. Grant Genie space access"
echo "  3. Upload Teams app: $TEAMS_PACKAGE (appears as: $BOT_SHORT_NAME)"
echo "  4. Test in Teams!"
echo ""
echo -e "${GREEN}Documentation: docs/${NC}"
echo ""

