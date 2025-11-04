# 🤖 Databricks Genie Teams Bot

A Microsoft Teams bot that connects to Databricks Genie using Azure AD OAuth authentication.

---

## 📁 Project Structure

```
db_app_genie_teams/
├── install.sh                  # 🌟 Main installation script (Azure CLI only)
├── function_app.py             # Azure Function entry point
├── config.py                   # Configuration management
├── requirements.txt            # Python dependencies
├── host.json                   # Function App config
├── bot/                        # Bot logic
│   └── teams_bot.py
├── databricks/                 # Databricks Genie client
│   └── genie_client.py
├── teams-app-package/          # Teams manifest & icons
│   ├── manifest.json
│   ├── color.png
│   └── outline.png
├── scripts/                    # Helper scripts
│   └── create_deployment_linux.sh
└── docs/                       # Documentation
    ├── README.md               # Detailed documentation
    └── deployment-credentials-*.txt
```

---

## 🚀 Installation (3 Steps)

### Prerequisites

- Azure subscription
- Azure CLI installed and logged in (`az login`)
- Azure Databricks workspace (Premium tier)
- Databricks Genie space

---

### Step 1: Configure

**Option A: Using .env file (Recommended)**

```bash
cp config.env .env
# Edit .env with your values
```

**Option B: Edit install.sh directly**

Edit `install.sh` and set your Databricks details in the configuration section.

---

### Step 2: Create Deployment Package

```bash
./scripts/create_deployment_linux.sh
```

This creates `databricks-genie-bot-deploy-linux.zip` with all Python dependencies.

---

### Step 3: Run Installation

```bash
chmod +x install.sh
./install.sh
```

**What it does (Azure CLI only):**
- ✅ Creates Resource Group
- ✅ Creates Storage Account
- ✅ Creates Function App
- ✅ Creates App Registration & Service Principal
- ✅ Generates client secret
- ✅ Adds Azure Databricks API permission
- ✅ Configures Function App settings
- ✅ Deploys code
- ✅ Creates Bot Service
- ✅ Enables Teams channel
- ✅ Creates Teams app package

**Time:** ~5 minutes

---

## 📋 Post-Deployment (Manual Steps)

After installation completes, you need to:

### 1. Add Service Principal to Databricks

1. Go to your Databricks workspace
2. Click **Settings** → **Admin Console**
3. Go to **Identity and access** → **Service principals**
4. Click **+ Add service principal**
5. Enter the **App ID** (from script output)
6. Click **Add**
7. Enable **"Workspace access"** entitlement

### 2. Grant Genie Space Access

1. Navigate to your Genie space
2. Click **Share**
3. Add the service principal (same App ID)
4. Grant permission: **Can use**
5. Click **Save**

### 3. Upload Teams App

1. Find file: `databricks-genie-teams-app-*.zip`
2. Upload to Teams Admin Center or Teams client
3. Add bot to Teams

---

## 🧪 Test

### In 1:1 Chat:
```
hello
explain my data
```

### In Channel:
```
@Databricks Genie hello
```

---

## 📊 Monitor

```bash
az webapp log tail \
  --name <your-function-app-name> \
  --resource-group databricks-genie-rg
```

---

## 📖 Documentation

See `docs/README.md` for detailed documentation.

---

## 🏗️ Architecture

```
Microsoft Teams → Azure Bot Service → Function App (Python)
                                      ↓ (Azure AD OAuth)
                                    Azure Databricks (Genie API)
```

**Authentication:** Azure AD Service Principal (no PAT tokens!)

---

## 📝 License

MIT
