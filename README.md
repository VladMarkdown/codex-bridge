# codex-bridge

A tiny **bridge** that lets [Claude Code](https://docs.claude.com/en/docs/claude-code) (or any tool, or you on the command line) consult **OpenAI Codex (GPT-5.x)** — a second model — for a second opinion, an alternative implementation, or to delegate a self-contained subtask.

It does one thing: authenticate once (Sign in with ChatGPT), then send a prompt to Codex and get the answer back. Everything else (code review flows, image generation, batch jobs) you build on top of the `ask()` / `respond()` primitives.

```bash
codex-bridge ask "Give me an alternative implementation of this LRU cache, then list trade-offs vs a dict + OrderedDict."
```

---

## Install

Requires Python 3.9+. Install as a CLI (puts `codex-bridge` on your PATH):

```bash
pipx install git+https://github.com/VladMarkdown/codex-bridge
# or:  pip install git+https://github.com/VladMarkdown/codex-bridge
# or, from a clone:  pipx install .
```

## Authenticate (once)

```bash
codex-bridge login
```

Opens a browser device-code flow — enter the shown code and approve in your
ChatGPT account. The token is stored **only on your machine** at
`~/.codex-bridge/auth.json` and is auto-refreshed. Check it with
`codex-bridge whoami`.

## Use

**CLI**

```bash
codex-bridge ask "your question"           # prints Codex's answer
codex-bridge ask "..." --model gpt-5.5     # pick the model
cat patch.diff | codex-bridge ask -        # read the prompt from stdin (best for code)
```

**As a library** (the bridge primitives)

```python
from codex_bridge import ask, respond, extract_text

# plain text / code
print(ask("Explain this stack trace and suggest a fix:\n" + trace))

# low-level: respond() returns the raw SSE stream, so you can use Codex tools.
# e.g. image generation — parse the image_generation_call result yourself:
sse = respond(
    "A flat icon of a wooden shield, chroma-green background",
    tools=[{"type": "image_generation", "model": "gpt-image-1.5",
            "size": "1024x1024", "output_format": "png"}],
    tool_choice={"type": "image_generation"},
)
```

## Use inside Claude Code (plugin)

This repo is also a Claude Code plugin (a skill + a `/codex` command).

```text
/plugin install codex-bridge@VladMarkdown/codex-bridge
```

Then either run `/codex-bridge:codex <your question>`, or just ask Claude to
"get a second opinion from Codex" — the skill tells it how to call the bridge
and to treat the answer as input to verify, not as truth.

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `CODEX_BRIDGE_HOME` | `~/.codex-bridge` | where the token is stored |
| `CODEX_BRIDGE_MODEL` | `gpt-5.5` | default model id |
| `CODEX_BRIDGE_ORIGINATOR` | `codex-bridge` | client identifier sent with requests |

## Notes

- Uses your own ChatGPT plan via the Codex "Sign in with ChatGPT" flow; usage
  counts against your plan's limits (overflow → buy credits or use an API key).
- The token never leaves your machine and is never printed or committed.
- Not affiliated with or endorsed by OpenAI. Use it with your own account.

## License

MIT — see [LICENSE](LICENSE).
