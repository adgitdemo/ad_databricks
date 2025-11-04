#!/bin/bash

# Create Deployment Package with Linux-Compatible Dependencies
# This builds packages for Azure Functions (Linux x86_64)

set -e

echo "🎁 Creating Linux-Compatible Deployment Package..."
echo "===================================================="
echo ""

# Set variables
PACKAGE_NAME="databricks-genie-bot-deploy-linux.zip"
TEMP_DIR="temp_deploy_linux"
PYTHON_VERSION="3.11"

# Check Python version
PYTHON_CMD="python3.11"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python3"
    if ! command -v $PYTHON_CMD &> /dev/null; then
        PYTHON_CMD="python"
    fi
fi

echo "🐍 Using Python: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# Clean up previous builds
echo "🧹 Cleaning up previous builds..."
rm -f "$PACKAGE_NAME"
rm -rf "$TEMP_DIR"

# Create temporary directory
echo "📁 Creating temporary directory..."
mkdir -p "$TEMP_DIR"

# Copy application files
echo "📦 Copying application files..."
cp -r bot "$TEMP_DIR/"
cp -r databricks "$TEMP_DIR/"
cp function_app.py "$TEMP_DIR/"
cp config.py "$TEMP_DIR/"
cp requirements.txt "$TEMP_DIR/"
cp host.json "$TEMP_DIR/"
# Note: .env files are not included in deployment package for security

# Remove any cached Python files
echo "🧹 Removing Python cache files..."
find "$TEMP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR" -type f -name "*.pyc" -exec rm -f {} + 2>/dev/null || true
find "$TEMP_DIR" -type f -name "*.pyo" -exec rm -f {} + 2>/dev/null || true
find "$TEMP_DIR" -type f -name ".DS_Store" -exec rm -f {} + 2>/dev/null || true

# Install dependencies for Linux platform
echo ""
echo "📥 Installing Python dependencies for LINUX..."
echo "   Target: Linux x86_64 (Azure Functions platform)"
echo "   This may take 2-3 minutes..."
echo ""

# Create the packages directory structure for Azure Functions
mkdir -p "$TEMP_DIR/.python_packages/lib/site-packages"

# Install all dependencies for Linux platform
$PYTHON_CMD -m pip install \
    --target "$TEMP_DIR/.python_packages/lib/site-packages" \
    --platform manylinux2014_x86_64 \
    --platform manylinux_2_17_x86_64 \
    --platform linux_x86_64 \
    --only-binary=:all: \
    --upgrade \
    --python-version 311 \
    --implementation cp \
    -r requirements.txt

echo ""
echo "✅ Linux-compatible dependencies installed!"
echo ""

# Show what was installed
echo "📋 Installed packages:"
ls -1 "$TEMP_DIR/.python_packages/lib/site-packages" | head -20
if [ $(ls -1 "$TEMP_DIR/.python_packages/lib/site-packages" | wc -l) -gt 20 ]; then
    echo "   ... and more"
fi
echo ""

# Verify we got Linux binaries
echo "🔍 Verifying Linux binaries..."
if ls "$TEMP_DIR/.python_packages/lib/site-packages"/**/*.so 2>/dev/null | head -1 > /dev/null; then
    SAMPLE_SO=$(ls "$TEMP_DIR/.python_packages/lib/site-packages"/**/*.so 2>/dev/null | head -1)
    echo "   Found .so files (Linux binaries)"
    file "$SAMPLE_SO" 2>/dev/null || echo "   Binary verification requires 'file' command"
fi
echo ""

# Clean up unnecessary files from packages to reduce size
echo "🧹 Cleaning up package files to reduce size..."
find "$TEMP_DIR/.python_packages" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$TEMP_DIR/.python_packages" -type d -name "*.dist-info" -exec rm -rf {}/RECORD + 2>/dev/null || true
find "$TEMP_DIR/.python_packages" -type f -name "*.pyc" -exec rm -f {} + 2>/dev/null || true
find "$TEMP_DIR/.python_packages" -type f -name "*.pyo" -exec rm -f {} + 2>/dev/null || true
find "$TEMP_DIR/.python_packages" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# Create .funcignore
echo "📝 Creating .funcignore..."
cat > "$TEMP_DIR/.funcignore" << 'EOF'
.git*
.vscode
local.settings.json
test
.venv
.env
EOF

# Create zip file
echo "🗜️  Creating zip package..."
cd "$TEMP_DIR"
zip -r "../$PACKAGE_NAME" . -x "*.pyc" -x "*__pycache__*" -x "*.DS_Store" > /dev/null
cd ..

# Clean up temporary directory
echo "🧹 Cleaning up..."
rm -rf "$TEMP_DIR"

# Get file size
FILE_SIZE=$(ls -lh "$PACKAGE_NAME" | awk '{print $5}')

echo ""
echo "✅ Linux-Compatible Deployment Package Created!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "📦 Package: $PACKAGE_NAME"
echo "📊 Size: $FILE_SIZE"
echo "🐧 Platform: Linux x86_64 (Azure Functions)"
echo ""
echo "📋 Contents:"
echo "  ✅ Application code (bot/, databricks/)"
echo "  ✅ Core files (function_app.py, config.py, etc.)"
echo "  ✅ ALL Python dependencies (Linux binaries)"
echo "  ✅ .python_packages/lib/site-packages/"
echo ""
echo "🚀 Ready to deploy to Azure Functions!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📝 Deployment Instructions:"
echo ""
echo "METHOD 1: Kudu (Easiest) ⭐"
echo "  1. Go to: https://YOUR-FUNCTION-APP.scm.azurewebsites.net"
echo "  2. Tools → Zip Push Deploy"
echo "  3. Upload: $PACKAGE_NAME"
echo "  4. Wait 1-2 minutes"
echo "  5. Check Functions page"
echo ""
echo "METHOD 2: Azure CLI"
echo "  az functionapp deployment source config-zip \\"
echo "    --resource-group databricks-genie-rg \\"
echo "    --name YOUR-FUNCTION-APP-NAME \\"
echo "    --src $PACKAGE_NAME"
echo ""
echo "METHOD 3: Blob Storage"
echo "  1. Upload to Azure Storage Container"
echo "  2. Generate SAS token"
echo "  3. Set WEBSITE_RUN_FROM_PACKAGE = <blob-url>"
echo "  4. Click 'Sync'"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "⚠️  VERIFY Function App settings:"
echo "  • PYTHON_ISOLATE_WORKER_DEPENDENCIES = 1"
echo "  • PYTHON_ENABLE_WORKER_EXTENSIONS = 1"
echo ""
echo "✅ This package will work on Azure Linux!"
echo ""

