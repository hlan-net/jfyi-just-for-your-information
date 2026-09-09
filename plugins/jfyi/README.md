# JFYI plugin for Claude Code

Installs from this repository's marketplace. Your instance URL and token are set once with `/plugin configure jfyi@jfyi` (or `--config`) and stored by Claude Code, the token in secure storage; nothing personal lives in this directory or in your project repos.

```bash
claude plugin marketplace add hlan-net/jfyi-just-for-your-information
claude plugin install jfyi@jfyi
# then, inside Claude Code:  /plugin configure jfyi@jfyi
```

See [docs/claude-code-plugin.md](../../docs/claude-code-plugin.md) for team, project and claude.ai/code setup.
