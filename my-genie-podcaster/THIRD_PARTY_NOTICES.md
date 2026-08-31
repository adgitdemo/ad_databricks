# Third-Party Notices

This project uses the following third-party components. Each is used under its
own license; the relevant terms and copyright notices are retained here in
accordance with those licenses.

## Text-to-speech

- **Kokoro-82M** — the speech synthesis model.
  - Model: `hexgrad/Kokoro-82M` and the ONNX build `onnx-community/Kokoro-82M-v1.0-ONNX`.
  - License: **Apache License 2.0**.
  - Built on the **StyleTTS 2** architecture (by @yl4579) and an ISTFTNet vocoder.
  - The model weights are downloaded/hosted separately (see the README); they are
    not redistributed in this repository.

- **kokoro-js** — JavaScript runtime for Kokoro (bundles the voice embeddings).
  - License: **Apache License 2.0**.

- **@huggingface/transformers** (Transformers.js) — ONNX model loading/runtime.
  - License: **Apache License 2.0**.

## Application framework & libraries

- **Databricks AppKit** and the **Databricks SDK** — application framework and API client.
- **React**, **React Router**, **Vite**, **Tailwind CSS**, **lucide-react**, **Express**,
  **pg**, **zod**, and other dependencies listed in `package.json`, each under its
  respective open-source license (see each package's `LICENSE`).

## Notes

- Copies of the Apache License 2.0 are distributed with the respective packages
  (e.g. `node_modules/kokoro-js/LICENSE`) and are available at
  <https://www.apache.org/licenses/LICENSE-2.0>.
- The narration produced by this app is **AI-generated speech** of **AI-generated
  Genie answers**; figures are summarized/rounded for listening and should be
  verified against the on-screen details before being relied upon.
