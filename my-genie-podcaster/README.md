# 🎙️ My Genie Podcaster

**Turn your Databricks Genie answers into a spoken podcast.** Pick a Genie space, type a few questions, and get a short audio episode where each answer is narrated in plain English — with the supporting numbers, SQL, and Genie's reasoning a tap away on screen.

Built as a [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) on the AppKit framework. Genie runs **on-behalf-of the signed-in user**, episodes are stored durably in **Lakebase**, and narration is generated in-app by **Kokoro-82M** text-to-speech.

---

## ✨ Features

- 🗣️ **Narrated answers** — each Genie summary is spoken aloud by an in-app voice model.
- 🧠 **No second LLM** — Genie itself writes the spoken summary; there's nothing else to host.
- 📊 **Details on tap** — the exact figures, generated SQL, Genie's reasoning, and result rows stay on screen.
- 🔐 **Runs as you** — every Genie query runs on-behalf-of the signed-in user, with their permissions.
- 💾 **Durable** — episodes live in Lakebase (Postgres), audio in a UC Volume; both survive redeploys.
- 🎚️ **Playback UX** — voice picker, sequential player, pre-generated + cached audio, seek, and prefetch.
- 📱 **Mobile-first** — a tiny bundle and a clean Databricks white-and-orange theme.

---

## 🛠️ Architecture

```
    Browser (React SPA)
        │  REST /api/*
    Databricks App  (Express via AppKit)
        ├─ Genie Conversation API   → runs on-behalf-of (OBO) the user
        ├─ Kokoro-82M TTS           → ONNX, CPU, in-app
        ├─ Lakebase (Postgres)      → episodes + segments + preferences
        └─ UC Volume                → narration WAVs + model weights
```

**How it works:** the browser posts a Genie space and questions. In the background the server asks Genie each question (as you), wrapping it so Genie returns a spoken `SUMMARY:` plus on-screen `DETAILS:`. Each answer is stored, its default-voice narration is synthesized and cached in the UC Volume, and the client streams the audio segment by segment.

---

## ✅ Prerequisites

- A **Databricks workspace** with **Databricks Apps** enabled.
- The **[Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)** (v1.10+; the `postgres` app-resource type requires a recent version), configured with an auth profile.
- A **Genie space** you can query — and access to its underlying data.
- Permission to create a **Lakebase (Postgres)** database and a **Unity Catalog Volume**.
- **Node.js 22+** and npm (for the local build and model download).

---

## ⚙️ Setup Instructions

### 1. Provision storage

- Create a **Lakebase** database. Note its **branch** and **database** identifiers (`projects/…/branches/…/databases/…`).
- Create a **UC Volume** in an existing catalog/schema for the audio and model. Note its path: `/Volumes/<catalog>/<schema>/<volume>`.

### 2. Configure the bundle

Edit **`databricks.yml`** and set:

- `targets.default.workspace.host` — your workspace URL.
- A **`postgres`** app resource with `permission: CAN_CONNECT_AND_CREATE` (the app creates and owns its own `podcast` schema), pointing at your **branch** and **database**.
- Two **`uc_securable`** VOLUME resources — one `READ_VOLUME` and one `WRITE_VOLUME`. *(WRITE does not imply READ — you need both.)*
- `user_api_scopes: [dashboards.genie]` so Genie can run on-behalf-of the user.

Edit **`app.yaml`** and set:

- `LAKEBASE_ENDPOINT` → `valueFrom: postgres` (resolved from the resource above).
- `DATABRICKS_VOLUME_AUDIO` → your Volume path, e.g. `/Volumes/<catalog>/<schema>/<volume>`.

### 3. Fetch and stage the TTS model

The Kokoro weights (~88 MB) exceed the workspace file-size limit, so they live in the Volume; the app copies them to local disk on first boot (no Hugging Face egress at runtime).

```bash
npm install
npm run setup:model   # downloads the model into ./.hf-cache/onnx-community/Kokoro-82M-v1.0-ONNX/

# create the target folder in your Volume (parents included)
databricks fs mkdir "dbfs:/Volumes/<catalog>/<schema>/<volume>/_models/onnx-community/Kokoro-82M-v1.0-ONNX/onnx"

# upload the four model files (paths must match exactly)
BASE=".hf-cache/onnx-community/Kokoro-82M-v1.0-ONNX"
VOL="dbfs:/Volumes/<catalog>/<schema>/<volume>/_models/onnx-community/Kokoro-82M-v1.0-ONNX"
databricks fs cp "$BASE/config.json"            "$VOL/config.json" --overwrite
databricks fs cp "$BASE/tokenizer.json"         "$VOL/tokenizer.json" --overwrite
databricks fs cp "$BASE/tokenizer_config.json"  "$VOL/tokenizer_config.json" --overwrite
databricks fs cp "$BASE/onnx/model_quantized.onnx" "$VOL/onnx/model_quantized.onnx" --overwrite
```

### 4. Build, deploy, and run

The bundle ships the compiled `dist/` and `client/dist/`, so build locally first.

```bash
npm run build
databricks bundle deploy --profile <your-profile>
databricks bundle run app --profile <your-profile>
```

Open the app URL printed at the end. The app compute installs its native dependencies and starts the server.

---

## 🚀 Usage

1. Tap **New**.
2. Enter a **Genie space** (by name or ID) and one or more **questions**.
3. Hit **Create podcast** — the app asks Genie, captures each `SUMMARY`/`DETAILS`, and pre-synthesizes the narration in the background.
4. Open the episode and press **Play**. Switch narrators from the **voice** picker, and expand **Detailed analysis** on any answer to see the figures, SQL, Genie's reasoning, and a preview of the rows. Use **Open conversation in Genie** to jump back to the underlying chat.

---

## 🧑‍💻 Local development

```bash
npm install
cp .env.example .env     # fill in for local dev (see comments in the file)
npm run dev              # hot-reloading dev server
npm test                 # unit tests (Vitest) + smoke tests (Playwright)
npm run typecheck        # type-check server + client
npm run lint             # ESLint
```

---

## 💡 Tips & Considerations

- **Per-user Genie access.** Genie runs as the signed-in user. If a user lacks access to a space's underlying data, Genie returns a permission error (`PERMISSION_DENIED: An error occurred accessing the schema`) — grant them access to the space and its tables.
- **Don't rename the deployed app casually.** Renaming a Databricks App mints a **new service principal**, and Postgres schema ownership doesn't transfer — the new identity can't touch the existing Lakebase schemas. Keep the app name stable, or migrate ownership when you rebrand.
- **First play vs. later plays.** The default voice is pre-generated during creation; other voices synthesize on first play and are then cached in the Volume.
- **Synthesis is CPU-only and serialized.** A multi-segment episode narrates sequentially (a few seconds per segment). Model load and synthesis are both time-boxed so a stall can never wedge generation.
- **Summaries are AI-generated.** The narration is spoken AI output with rounded numbers — verify figures against the on-screen details before relying on them.

---

## 📁 Project structure

```
server/      Express backend (Genie, TTS, storage, routes)
client/      React + Vite frontend (list / create / detail+player)
shared/      Types shared by client and server
scripts/     Model pre-warm helper
databricks.yml, app.yaml   Databricks App bundle + runtime config
```

---

## 📄 License & credits

Speech synthesis is powered by **[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)** (Apache-2.0), built on **StyleTTS 2**, via **kokoro-js** and **Transformers.js** (both Apache-2.0). See [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) for full attribution.

*Powered by Databricks Genie.* 🎧
