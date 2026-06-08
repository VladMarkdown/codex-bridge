---
description: Consult OpenAI Codex (GPT-5.x), a second model, from inside Claude Code. Use when you want a second opinion on a tricky bug or design, an alternative implementation, a cross-check of your own answer, or to delegate a self-contained coding subtask to another model. Requires the `codex-bridge` CLI installed and `codex-bridge login` done once.
---

# Consulting Codex (a second model)

`codex-bridge` is a small CLI that sends a prompt to OpenAI Codex (GPT-5.x) and
prints the answer. Use it to bring a **second model's perspective** into the
session — not to replace your own reasoning, but to compare against it.

## When this is useful
- You're stuck on a bug and want an independent diagnosis.
- You want a second design/implementation to compare with yours.
- You want to cross-check an answer you're unsure about.
- A self-contained subtask is worth offloading to another model.

## How to call it
Run via Bash. For short prompts:

```bash
codex-bridge ask "Your question. Be specific and self-contained — Codex has no access to this repo."
```

For long prompts or when you need to include a code snippet, pipe via stdin to
avoid shell-quoting problems:

```bash
cat <<'EOF' | codex-bridge ask -
Review this function for correctness and edge cases:

<paste code here>
EOF
```

Pick the model with `--model` if needed (default is GPT-5.x):
`codex-bridge ask "..." --model gpt-5.5`

## Important
- **Codex cannot see the repo or this conversation.** Put everything it needs
  *into the prompt* (the relevant code, the error, the constraints).
- Treat its answer as **input, not truth** — verify against the actual code and
  your own judgment before acting on it.
- If you get `Not logged in`, tell the user to run `codex-bridge login` once.
- Usage counts against the user's own ChatGPT plan limits.
