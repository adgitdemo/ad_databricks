#!/bin/bash

# Full deployment script that provisions all Azure resources, creates the bot
# identity (App Registration + service principal), deploys the Function App
# package, and enables the Microsoft Teams channel. This version is designed to
# be idempotent and will create fresh names on each run by appending a timestamp
# suffix.

set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# USER CONFIGURATION – EDIT BEFORE RUNNING
# ═══════════════════════════════════════════════════════════════

# Base naming prefix. A timestamp is appended automatically.
NAME_PREFIX="db-genie"
RESOURCE_GROUP="databricks-genie-rg"
LOCATION="eastus"

# Databricks configuration (required) - EDIT THESE!
DATABRICKS_HOST="https://adb-271413217994145.5.azuredatabricks.net"
DATABRICKS_GENIE_SPACE_ID="01f0b8ebb6e01f9a8f75ec08bb1e70ba"

# Deployment package generated via create_deployment_linux.sh
PACKAGE_FILE="databricks-genie-bot-deploy-linux.zip"

LOG_LEVEL="INFO"

# ═══════════════════════════════════════════════════════════════
# DERIVED NAMES
# ═══════════════════════════════════════════════════════════════

TIMESTAMP=$(date +%Y%m%d%H%M%S)
UNIQUE_SUFFIX="${TIMESTAMP}"
FUNCTION_APP_NAME="${NAME_PREFIX}-func-${UNIQUE_SUFFIX}"
BOT_NAME="${NAME_PREFIX}-bot-${UNIQUE_SUFFIX}"
BOT_DISPLAY_NAME="Databricks Genie Bot ${TIMESTAMP}"
STORAGE_ACCOUNT_RAW="${NAME_PREFIX//-/}${UNIQUE_SUFFIX}"     # remove dashes for storage account
STORAGE_ACCOUNT=$(echo "${STORAGE_ACCOUNT_RAW}" | tr '[:upper:]' '[:lower:]')
STORAGE_ACCOUNT=${STORAGE_ACCOUNT:0:24}  # storage account max 24 chars
CREDS_NOTE="deployment-credentials-${UNIQUE_SUFFIX}.txt"

# ═══════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

function header() {
  echo "${BLUE}══════════════════════════════════════════════════════════════${NC}"
  echo "${BLUE}  $1${NC}"
  echo "${BLUE}══════════════════════════════════════════════════════════════${NC}"
}

# ═══════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║     🚀 Databricks Genie Bot (Service Principal Deploy) 🚀  ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

if [ -z "$DATABRICKS_HOST" ] || [ -z "$DATABRICKS_GENIE_SPACE_ID" ]; then
  echo -e "${RED}❌ Databricks configuration missing.${NC} Edit the script and set:\n  • DATABRICKS_HOST\n  • DATABRICKS_GENIE_SPACE_ID"
  exit 1
fi

if [ ! -f "$PACKAGE_FILE" ]; then
  echo -e "${RED}❌ Deployment package not found: $PACKAGE_FILE${NC}"
  echo "   Run ./create_deployment_linux.sh first."
  exit 1
fi

echo -e "${BLUE}Configuration Summary${NC}"
echo "  Resource Group : $RESOURCE_GROUP"
echo "  Location       : $LOCATION"
echo "  Function App   : $FUNCTION_APP_NAME"
echo "  Bot Service    : $BOT_NAME"
echo "  Storage Account: $STORAGE_ACCOUNT"
echo "  App Display    : $BOT_DISPLAY_NAME"
echo "  Package File   : $PACKAGE_FILE"
echo ""

read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Deployment cancelled."
  exit 0
fi

# ═══════════════════════════════════════════════════════════════
# STEP 1 – RESOURCE GROUP
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

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 2 – STORAGE ACCOUNT
# ═══════════════════════════════════════════════════════════════

header "Step 2/11: Ensuring Storage Account"
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

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 3 – FUNCTION APP
# ═══════════════════════════════════════════════════════════════

header "Step 3/11: Ensuring Function App"
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

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 4 – APP REGISTRATION
# ═══════════════════════════════════════════════════════════════

header "Step 4/11: Creating App Registration"
APP_ID=$(az ad app create \
  --display-name "$BOT_DISPLAY_NAME" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

if [ -z "$APP_ID" ]; then
  echo -e "${RED}❌ Failed to create Azure AD app registration${NC}"
  exit 1
fi

echo -e "${GREEN}✅ App Registration created${NC}"
echo "   App ID: $APP_ID"
TENANT_ID=$(az account show --query tenantId -o tsv)
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
echo "   Tenant ID: $TENANT_ID"
echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 5 – SERVICE PRINCIPAL
# ═══════════════════════════════════════════════════════════════

header "Step 5/11: Creating/Verifying Service Principal"
if az ad sp show --id "$APP_ID" >/dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Service principal already exists${NC}"
else
  az ad sp create --id "$APP_ID" >/dev/null
  echo -e "${GREEN}✅ Service principal created${NC}"
fi

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 6 – CLIENT SECRET
# ═══════════════════════════════════════════════════════════════

header "Step 6/11: Generating Client Secret"
APP_SECRET=$(az ad app credential reset \
  --id "$APP_ID" \
  --display-name "deploy-${UNIQUE_SUFFIX}" \
  --query password -o tsv)

echo -e "${GREEN}✅ Client secret generated${NC}"
echo -e "${YELLOW}⚠️  Save this secret securely: $APP_SECRET${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 6.5 – ADD AZURE DATABRICKS API PERMISSION
# ═══════════════════════════════════════════════════════════════

header "Step 6.5/11: Adding Azure Databricks API Permission"

# Azure Databricks resource ID and permission ID
DATABRICKS_RESOURCE_ID="2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
USER_IMPERSONATION_ID="d284fb2b-8c8e-4b89-9e81-03a36a477ac3"

# Add permission
az ad app permission add \
  --id "$APP_ID" \
  --api "$DATABRICKS_RESOURCE_ID" \
  --api-permissions "${USER_IMPERSONATION_ID}=Scope" \
  --output none 2>/dev/null || true

# Grant admin consent
az ad app permission grant \
  --id "$APP_ID" \
  --api "$DATABRICKS_RESOURCE_ID" \
  --scope "user_impersonation" \
  --output none 2>/dev/null || echo -e "${YELLOW}Note: Admin consent may need to be granted manually${NC}"

echo -e "${GREEN}✅ Azure Databricks API permission added${NC}"
echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 7 – APP SETTINGS
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

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 8 – DEPLOY CODE
# ═══════════════════════════════════════════════════════════════

header "Step 8/11: Deploying Function Code"
az functionapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --src "$PACKAGE_FILE" \
  --output none

echo -e "${GREEN}✅ Code deployed${NC}"

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 9 – BOT SERVICE
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

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 10 – ENABLE TEAMS CHANNEL
# ═══════════════════════════════════════════════════════════════

header "Step 10/11: Enabling Microsoft Teams Channel"
az bot msteams create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$BOT_NAME" \
  --output none

echo -e "${GREEN}✅ Teams channel enabled${NC}"

echo ""

# ═══════════════════════════════════════════════════════════════
# STEP 11 – RESTART FUNCTION APP
# ═══════════════════════════════════════════════════════════════

header "Step 11/11: Restarting Function App"
az functionapp restart \
  --name "$FUNCTION_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --output none

echo -e "${GREEN}✅ Function App restarted${NC}"

echo ""

# ═══════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════

HEALTH_URL="https://$FUNCTION_HOST/api/health"
cat <<SUMMARY
╔════════════════════════════════════════════════════════════╗
║                    Deployment Summary                     ║
╚════════════════════════════════════════════════════════════╝
Resource Group : $RESOURCE_GROUP ($LOCATION)
Function App   : $FUNCTION_APP_NAME
Bot Service    : $BOT_NAME
App ID         : $APP_ID
Tenant ID      : $TENANT_ID
Secret (copy)  : $APP_SECRET
Endpoint       : $MESSAGING_ENDPOINT
Health Check   : $HEALTH_URL

Next steps:
  1. Add service principal to Databricks:
     • Go to: $DATABRICKS_HOST
     • Admin Console → Identity and access → Service principals
     • Click: + Add service principal
     • Enter: $APP_ID
     • Click: Add
  
  2. Grant Genie space access:
     • Navigate to Genie space: $DATABRICKS_GENIE_SPACE_ID
     • Click: Share
     • Add service principal: $APP_ID
     • Permission: Can use
  
  3. Upload Teams app manifest:
     • Upload: databricks-genie-teams-app-${APP_ID:0:8}.zip
     • Teams Admin Center or Teams client

⚠️  Save the secret securely. Rotate it regularly or store in Key Vault.
SUMMARY

# Optionally write credentials to a note (disabled by default).
echo -e "${YELLOW}⚠️  Credentials printed above. Consider storing them in a secure vault.${NC}"
