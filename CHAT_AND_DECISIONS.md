# Chat, decisions, and history

## Chat: independent conversations with local and cloud models

Open **＋ Chat** to start an independent session. Tabs remain separate even when they share a connection. Agentnik supports OpenAI-compatible **Responses**, **Chat Completions**, and **Anthropic Messages**, plus native Ollama chat. Actual model capabilities depend on the endpoint.

- Stream replies with Markdown and wrapped code blocks; turn streaming off when an endpoint requires it.
- Expand or hide inline thinking, and select reasoning effort for models that support it. Thinking uses smaller, subdued text to distinguish it from the response.
- Copy an assistant response with its original Markdown using the **⧉** icon, including text received so far during streaming.
- Edit and resend a previous prompt with **✎**, restoring its text and images to the composer while preserving earlier history.
- Attach multiple PNG, JPEG, WebP, or GIF images through the file picker, drag and drop, or clipboard paste. Preview them in request order and double-click to open a stored copy. Model image support varies.
- **Document Reader:** attach text/Markdown/CSV/JSON, PDF, DOCX, and XLSX with local preview. PDFs default to page images **and** extracted text for multimodal models; turn off page images for text-only models. Preview/remove document chips, drop documents into the composer, and restore them when editing a sent prompt. Extracted snapshots persist with drafts, history, saved prompts, and JSON exports. Original document binaries are not retained. Files stay local until Send. Limits: four documents per prompt, 10 MB each, 48,000 extracted characters, 100 PDF text pages or 12 image pages per import. Scanned PDFs work through page images; OCR and spreadsheet formula evaluation are not included.
- **Calculator / Data tools:** opt into model-requested local arithmetic and bounded CSV/JSON statistics without enabling Web access. Numeric summaries include missing values and optional groups. Code Heavy also has these tools. No arbitrary code executes; results use approximate floating-point arithmetic.
- Resize the composer; Agentnik remembers its height. Drafts and attachments remain available after failed or cancelled requests.
- Keep Web access controls beside session export at the bottom of the pane, with run status in the status bar.

## Decision: structured System One queries

Open **＋ Decision** to use Ollama's structured `/v1/systemone` API with a compatible decision model. Build one request containing shared state/context, optional JSON state, multiple images, and multiple named questions:

| Question | Configuration and display |
| --- | --- |
| Yes / No | Probability of yes and no |
| Multiple choice | 2–26 unique labels with descriptions; probability bars and an optional pie chart |
| Ordered score | 2–10 descriptions ordered from lowest to highest; returned scoring legend when available |

Images can be attached, dropped, or pasted into the state field. Image-only queries receive a short supplied state. Completed runs preserve the submitted form and raw response; **Restore query to form** makes an older query editable. Confidence is displayed separately from probability. Selecting a Decision tab requires a compatible decision model and endpoint.

## Prompts, history, and everyday controls

- Save chat drafts or complete decision forms with **Save prompt**, or star a past message/run. Give the prompt a name or accept the default. Search the collapsible Prompts panel and restore a prompt with **Copy to tab** or a double-click. Saved prompts survive restarts and history clearing.
- Search, rename, delete, and export saved sessions. Clear all history requires confirmation. Drafts and form edits save automatically; malformed or newer-version records remain preserved as unavailable sessions.
- Images are copied into application storage and shared by content hash, so history survives moved originals. JSON session exports include local attachment paths rather than bundled image files or credentials.
- View reported input/output tokens, current input context, effective context limit when known, elapsed time, and available processing/generation rates. Missing measurements remain unknown; thinking time is an estimate when available.
- Choose light, dark, or system theme; adjust font size from 8–32 points with **A− / A+**. Sidebar visibility and composer sizing are remembered.
- Use **Ctrl+Enter** to send, **Ctrl+B** to toggle history, and **Ctrl+N** for a new chat.
- Select the **Korean preview** and restart to try translated controls. English remains the fallback; other planned languages and full Korean coverage are still in progress.

Background requests keep the interface responsive and tabs independent. Cancellation stops accepting results and scheduling more work; remote processing or billing may continue until the server stops. A shared worker limit bounds background work.
