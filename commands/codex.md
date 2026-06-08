---
description: Ask OpenAI Codex (GPT-5.x) a question and show its answer.
---

Run the `codex-bridge` CLI to send the following request to OpenAI Codex
(GPT-5.x, a second model) and report its answer back to me.

Request: $ARGUMENTS

Steps:
1. Run it via Bash. For a short request:
   `codex-bridge ask "$ARGUMENTS"`
   If the request contains code or shell-special characters, pipe it via stdin
   instead (`... | codex-bridge ask -`) to avoid quoting issues.
2. Show me Codex's answer verbatim, then add your own brief take: do you agree,
   and would you do anything differently? Verify any claims against the actual
   code before acting on them.
3. If it prints `Not logged in`, tell me to run `codex-bridge login` once.
