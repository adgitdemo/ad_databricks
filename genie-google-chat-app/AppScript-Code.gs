/**
 * Databricks Genie Bot For Google Chat
 * Features: Context Awareness, Rich Cards, SQL Transparency, Robust Polling
 */

// CONFIGURATION
const DATABRICKS_HOST = 'https://dbc-xxxxxxxxxxx.cloud.databricks.com'; 
const DATABRICKS_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
const GENIE_SPACE_ID = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';
const DEBUG_MODE = false; // Set to true to log detailed API responses

/**
 * Responds to a message in Google Chat.
 */
function onMessage(event) {
  const startTime = new Date().getTime();
  
  try {
    const userMessage = event.chat.messagePayload.message.text;

    // 1. Start Genie Conversation
    const startResp = callGenieAPI(`spaces/${GENIE_SPACE_ID}/start-conversation`, 'POST', { content: userMessage });
    const conversationId = startResp.conversation_id;
    const messageId = startResp.message_id;

    // 2. Poll Genie
    const result = pollGenieSafe(conversationId, messageId, startTime);
    
    // 3. Extract Answer Text
    let botText = "Genie finished, but returned no text.";
    if (result.status === 'TIMEOUT') {
      botText = `⏱️ Genie is taking too long. <${DATABRICKS_HOST}/genie/spaces/${GENIE_SPACE_ID}/conversations/${conversationId}|Click to view answer>.`;
    } else if (result.attachments) {
      const textAtt = result.attachments.find(a => a.text);
      if (textAtt) botText = textAtt.text.content;
    }

    // 4. Return Card with Feedback Buttons
    const cardContent = buildFeedbackCard(botText, conversationId, messageId, false);
    
    return {
      hostAppDataAction: {
        chatDataAction: {
          createMessageAction: {
            message: cardContent
          }
        }
      }
    };

    // 4. Return Card with Feedback Buttons
    // We use buildFeedbackCard to keep the JSON clean
    // return buildFeedbackCard(botText, conversationId, messageId, false);

  } catch (e) {
    console.error("CRITICAL ERROR:", e);
    return {
      hostAppDataAction: {
        chatDataAction: {
          createMessageAction: {
            message: { text: `⚠️ **Error:** ${e.message}` }
          }
        }
      }
    };
  }
}

function submitFeedback(event) {
  const params = event.commonEventObject.parameters;
  const conversationId = params.convId;
  const messageId = params.msgId;
  const vote = params.vote;
  const originalText = params.answerText; // Retrieve the original answer

  try {
    // 1. Send API Call
    const endpoint = `spaces/${GENIE_SPACE_ID}/conversations/${conversationId}/messages/${messageId}/feedback`;
    callGenieAPI(endpoint, 'POST', { rating: vote });

    // 2. Rebuild the card (With Answer + "Sent" status)
    const cardJson = buildFeedbackCard(originalText, conversationId, messageId, true);

    // 3. Update the existing message in place
    return {
      hostAppDataAction: {
        chatDataAction: {
          updateMessageAction: {
            message: cardJson // Pass the full card structure, not just text
          }
        }
      }
    };

  } catch (e) {
    // If error, create a NEW message so we don't destroy the original answer
    return {
       hostAppDataAction: {
        chatDataAction: {
          createMessageAction: {
             message: { text: `⚠️ Error sending feedback: ${e.message}` }
          }
        }
      }
    };
  }
}

// --- HELPER FUNCTIONS ---

/**
 * Polls Genie with safety timeout
 */
function pollGenieSafe(conversationId, messageId, startTime) {
  while (true) {
    if ((new Date().getTime() - startTime) > 25000) return { status: 'TIMEOUT' };

    const resp = callGenieAPI(
      `spaces/${GENIE_SPACE_ID}/conversations/${conversationId}/messages/${messageId}`, 
      'GET'
    );
    
    if (resp.status === 'COMPLETED') return resp;
    if (resp.status === 'FAILED') throw new Error(`Genie Query Failed: ${JSON.stringify(resp.error)}`);

    Utilities.sleep(2000); 
  }
}

/**
 * Generic API Call
 */
function callGenieAPI(endpoint, method, payload) {
  const url = `${DATABRICKS_HOST}/api/2.0/genie/${endpoint}`;
  const options = {
    method: method,
    contentType: 'application/json',
    headers: { 'Authorization': `Bearer ${DATABRICKS_TOKEN}` },
    muteHttpExceptions: true
  };
  if (payload) options.payload = JSON.stringify(payload);

  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() >= 400) {
    throw new Error(`API Error: ${response.getContentText()}`);
  }
  return JSON.parse(response.getContentText());
}

function buildFeedbackCard(text, conversationId, messageId, isFeedbackSent) {
  const cardId = `genie-${messageId}-${new Date().getTime()}`;
  const sections = [];

  // Section 1: The Answer (Always visible)
  sections.push({
    widgets: [{
      textParagraph: { text: text }
    }]
  });

  // Section 2: Feedback Area
  if (isFeedbackSent) {
    // STATE B: Feedback already sent -> Show confirmation text
    sections.push({
      widgets: [{
        textParagraph: { 
          text: "<i>✅ Feedback sent to Genie</i>" 
        }
      }]
    });
  } else {
    // STATE A: No feedback yet -> Show Buttons
    if (conversationId && messageId) {
      sections.push({
        widgets: [{
          buttonList: {
            buttons: [
              {
                text: "👍 Good",
                onClick: {
                  action: {
                    function: "submitFeedback",
                    parameters: [
                      { key: "vote", value: "POSITIVE" },
                      { key: "convId", value: conversationId },
                      { key: "msgId", value: messageId },
                      { key: "answerText", value: text || "" } // SAVE THE TEXT HERE
                    ]
                  }
                }
              },
              {
                text: "👎 Bad",
                onClick: {
                  action: {
                    function: "submitFeedback",
                    parameters: [
                      { key: "vote", value: "NEGATIVE" },
                      { key: "convId", value: conversationId },
                      { key: "msgId", value: messageId },
                      { key: "answerText", value: text || "" } // SAVE THE TEXT HERE
                    ]
                  }
                }
              }
            ]
          }
        }]
      });
    }
  }

  // Return the correct wrapper based on whether we are creating or updating
  // (The calling function decides the wrapper, this just returns the card content)
  return {
    cardsV2: [{
      cardId: cardId,
      card: {
        header: { title: "Databricks Genie" },
        sections: sections
      }
    }]
  };
}

function onAddedToSpace(event) {
  return { hostAppDataAction: { chatDataAction: { createMessageAction: { message: { text: "Genie Bot Ready!" } } } } };
}

function onRemovedFromSpace(event) { console.info("Bot removed"); }