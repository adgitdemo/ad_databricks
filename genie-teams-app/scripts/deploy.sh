#!/bin/bash

# ═══════════════════════════════════════════════════════════════
# Databricks Genie Teams Bot - Complete Deployment Script
# ═══════════════════════════════════════════════════════════════
# This script does EVERYTHING:
# 1. Creates deployment package
# 2. Creates all Azure resources
# 3. Configures bot and authentication
# 4. Deploys code
# 5. Creates Teams app package
# 6. Provides post-deployment instructions
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ═══════════════════════════════════════════════════════════════
# USER CONFIGURATION – EDIT BEFORE RUNNING
# ═══════════════════════════════════════════════════════════════

# Databricks Configuration (REQUIRED)
DATABRICKS_HOST="https://adb-271413217994145.5.azuredatabricks.net"
DATABRICKS_GENIE_SPACE_ID="01f0b8ebb6e01f9a8f75ec08bb1e70ba"

# Azure Configuration
RESOURCE_GROUP="databricks-genie-rg"
LOCATION="eastus"
NAME_PREFIX="db-genie"

# Optional
LOG_LEVEL="INFO"

# ═══════════════════════════════════════════════════════════════

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║      🚀 Databricks Genie Teams Bot - Full Deploy 🚀       ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════════════════════

echo -e "${BLUE}Pre-flight checks...${NC}"
echo ""

# Check Azure CLI
if ! command -v az &> /dev/null; then
    echo -e "${RED}❌ Azure CLI not found. Please install: https://aka.ms/install-azure-cli${NC}"
    exit 1
fi
echo "✓ Azure CLI installed"

# Check logged in
if ! az account show &> /dev/null; then
    echo -e "${RED}❌ Not logged into Azure. Run: az login${NC}"
    exit 1
fi
echo "✓ Logged into Azure"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 not found${NC}"
    exit 1
fi
echo "✓ Python 3 installed"

# Check jq
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠️  jq not found (optional, for better output)${NC}"
fi

echo ""
echo -e "${BLUE}Configuration:${NC}"
echo "  Databricks Host : $DATABRICKS_HOST"
echo "  Genie Space ID  : $DATABRICKS_GENIE_SPACE_ID"
echo "  Resource Group  : $RESOURCE_GROUP"
echo "  Location        : $LOCATION"
echo ""

read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 0
fi

# ═══════════════════════════════════════════════════════════════
# STEP 1: CREATE DEPLOYMENT PACKAGE
# ═══════════════════════════════════════════════════════════════

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  STEP 1/2: Creating Deployment Package${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

if [ -f "databricks-genie-bot-deploy-linux.zip" ]; then
    echo -e "${YELLOW}⚠️  Deployment package exists. Recreating...${NC}"
    rm -f databricks-genie-bot-deploy-linux.zip
fi

if [ -f "create_deployment_linux.sh" ]; then
    chmod +x create_deployment_linux.sh
    ./create_deployment_linux.sh
else
    echo -e "${RED}❌ create_deployment_linux.sh not found${NC}"
    exit 1
fi

if [ ! -f "databricks-genie-bot-deploy-linux.zip" ]; then
    echo -e "${RED}❌ Failed to create deployment package${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ Deployment package ready${NC}"

# ═══════════════════════════════════════════════════════════════
# STEP 2: RUN INSTALLATION SCRIPT
# ═══════════════════════════════════════════════════════════════

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  STEP 2/2: Deploying to Azure${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""

if [ -f "install_teams_bot.sh" ]; then
    chmod +x install_teams_bot.sh
    # Run with automatic yes
    echo "y" | ./install_teams_bot.sh
else
    echo -e "${RED}❌ install_teams_bot.sh not found${NC}"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# COMPLETION
# ═══════════════════════════════════════════════════════════════

echo ""
echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║                 ✅ DEPLOYMENT COMPLETE! ✅                 ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}All Azure resources have been created and configured!${NC}"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  NEXT STEPS (Manual - Required)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "See DEPLOYMENT_CREDENTIALS.txt for all credentials and IDs"
echo ""
echo "1️⃣  Add Service Principal to Databricks"
echo "   ────────────────────────────────────"
echo "   • Go to: $DATABRICKS_HOST"
echo "   • Admin Console → Identity and access → Service principals"
echo "   • Click: + Add service principal"
echo "   • Enter the App ID from DEPLOYMENT_CREDENTIALS.txt"
echo "   • Click: Add"
echo "   • Enable 'Workspace access' entitlement"
echo ""
echo "2️⃣  Grant Genie Space Access"
echo "   ─────────────────────────"
echo "   • Navigate to Genie space: $DATABRICKS_GENIE_SPACE_ID"
echo "   • Click: Share"
echo "   • Add the service principal (App ID from above)"
echo "   • Permission: Can use"
echo "   • Click: Save"
echo ""
echo "3️⃣  Upload Teams App"
echo "   ──────────────────"
echo "   • File: databricks-genie-teams-app-*.zip"
echo "   • Upload to Teams Admin Center or Teams client"
echo "   • Add bot to Teams"
echo ""
echo "4️⃣  Test the Bot"
echo "   ─────────────"
echo "   • In Teams, send: hello"
echo "   • Try: explain my data"
echo ""
echo -e "${YELLOW}⚠️  Important: Save the credentials from DEPLOYMENT_CREDENTIALS.txt${NC}"
echo ""

