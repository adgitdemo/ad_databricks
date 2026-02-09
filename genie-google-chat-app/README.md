
# Databricks Genie Google Chat App Integration

## Integrate Databricks Genie with Google Chat Natively

Talk to your data directly from Google Chat—powered by Databricks AI/BI Genie and a Google Chat App built with Apps Script. This integration allows your team to query business data using natural language without needing SQL knowledge or switching tools.


## ✨ Features

*   **Conversational AI in Google Chat:** Ask questions like "What were total sales last quarter?" and get instant, data-backed answers.
*   **Rich Card Responses:** Results are displayed as formatted Google Chat Cards, including data tables and the generated SQL query.
*   **Response Feedback Loop:** Thumbs up/down buttons send ratings back to Databricks Genie, allowing space authors to review and improve answer quality.
*   **Direct Messages and @Mentions:** Works in 1:1 DMs with the bot or by @mentioning it in any Chat Space.
*   **No Infrastructure Required:** Runs entirely on Google Apps Script (serverless), eliminating the need to manage servers or deploy a separate Databricks App.
*   **Secure by Default:** Credentials are securely stored in the Apps Script Properties Service, and data access is governed by Databricks Unity Catalog.

## 🛠️ Architecture / How It Works

The integration connects three primary components:

1.  **Google Chat App:** Receives user messages and delivers rich card responses.
2.  **Google Apps Script (Middleware):** Acts as the serverless backend. It handles Chat events, calls the Databricks Genie API via REST, polls for query completion, formats the results into Chat Cards (Cards V2), and sends them back. All logic is contained within the script.
3.  **Databricks Genie API:** Processes the natural language question, generates the corresponding SQL, executes it against your DBSQL Warehouse, and returns the results. It leverages your Unity Catalog metadata and Genie Space configuration for accuracy.

##  Prerequisites

*   A **Google Workspace** account (Enterprise plan recommended) with admin access.
*   A **Databricks workspace** with a SQL Pro or Serverless warehouse.
*   A [curated **Genie Space**](https://docs.databricks.com/aws/en/genie/best-practices) containing your data sources, knowledge store, and sample queries.

## ⚙️ Setup Instructions

### 1. Databricks Setup: Space and Token

1.  **Set up Genie Space:**
    *   In your Databricks workspace, navigate to **Genie**.
    *   Create a new Genie space, add your data sources, and click **Create**.
    *   From the **Settings** tab, note the **Space ID** (a 32-character string).
2.  **Generate a Databricks Token:**
    *   In your Databricks workspace, click your username (top right) then **Settings**.
    *   Go to **Developer** > **Access Tokens**.
    *   Click **Generate New Token**, provide a description (e.g., "Google Chat Genie Bot"), and **copy the token immediately**.
3.  **Note your Workspace URL:** (e.g., `https://your-instance.cloud.databricks.com`).


### 2. Google Cloud Project Setup

1.  Go to the **Google Cloud Console** ([console.cloud.google.com](https://console.cloud.google.com)).
2.  Create a new project or select an existing one.
3.  Navigate to **APIs and Services** > **Library**, search for **Google Chat API**, and click **Enable**.
4.  Go to **APIs and Services** > **OAuth consent screen**. Select **Internal** and complete the required app information (e.g., "Genie Data Bot").

### 3. Create the Apps Script Project

1.  Go to **script.google.com** and click **New project**.
2.  Rename the project (e.g., **Genie Chat Bot**).
3.  Download all project files from this repository and create the corresponding files in the Apps Script editor:
    *   `Code.gs` (Chat event handlers and API logic)
    *   `appscript.json` (App Script configuration manifest)
4.  **Configure Script Properties** (Recommended):
    *   Go to **Project Settings** (gear icon).
    *   Under "**Script Properties**", click **Add script property** and add the following keys/values from Step 1:
        *   `DATABRICKS_TOKEN` = your Databricks Token
        *   `GENIE_SPACE_ID` = your Genie Space ID
        *   `DATABRICKS_HOST` = your Workspace URL (no trailing slash)

### 4. Configure and Deploy the Google Chat App

1.  In Apps Script, click **Deploy** > **New Deployment**, select **Add-on** configuration, and click **Deploy**.
2.  **Copy the Deployment ID** once the process is complete.
3.  Back in the **Google Cloud Console**, go to **APIs and Services** > **Google Chat API** > **Configuration**.
4.  Fill in the details:
    *   **App name:** `db-genie-1`
    *   **Description:** Databricks Genie Bot
    *   **Functionality:** Check "Join spaces and group conversations"
    *   **Connection settings:** Select **Apps Script** and paste your **Deployment ID** in the field.
    *   **Visibility:** Select "Specific people and groups" and add your team or test users.
5.  **Deploy:** The deployment step from the Apps Script editor should have already authorized the script.

## 🚀 Usage and Testing

1.  Open **Google Chat** and start a direct message with your bot (search for "Genie Data Bot").
2.  **Send a test question:** "What were total sales last month?"

The bot will return a rich card with the natural language answer and feedback buttons.

### Interaction Modes

*   **Direct Messages:** Open a DM with Genie Data Bot and type your question directly.
*   **@Mentions in Spaces:** In any Google Chat Space where the bot is added, type `@db-genie-1` followed by your question. Follow-ups can be asked in the thread.

**Example questions:**
*   "What were total sales last quarter?"
*   "Show me the top 10 customers by revenue"
*   "How many orders were placed this month?"
*   "Break that down by region" (as a follow-up)

## 💡 Tips and Considerations

*   **Answer Quality:** The quality of answers is directly dependent on the curation of your Genie Space. Add detailed table/column descriptions, sample SQL, and company-specific context.
*   **Sync Timeout:** Google Apps Script has a **30-second synchronous response limit** for Chat messages. If your Genie queries frequently take longer, consider implementing the **optional async pattern** using time-driven triggers and the Advanced Chat Service (detailed in the full repository README).
*   **Rate Limits:** The Genie API typically allows approximately 5 queries per minute per workspace during Public Preview.
*   **Row Limits:** Genie returns up to 5,000 rows per query. The Chat card displays up to 20 rows for readability, with a link to view full results in Genie.
