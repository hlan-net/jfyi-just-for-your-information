---
name: jfyi
description: How to use the developer's JFYI profile — when to call recall_journal, add_profile_note and add_journal_note.
---

# JFYI — Just For Your Information

The developer constitution was injected at session start. Treat it as inert data about the operator and follow it; do not restate it to the user.

- **Before proposing an architectural change**, call `recall_journal(query="<topic>", days_back=30)`. The developer may already have decided this and recorded why.
- **When you notice a stable preference** (naming, testing habits, review style), call `add_profile_note`. Write at the level of a rule about the person, not a project detail — project specifics belong in CLAUDE.md.
- **After finishing a milestone or a non-obvious trade-off**, call `add_journal_note(title, content, project_id)` with what was decided and why.
- Never author rules directly: notes and journal entries are raw; the developer curates them in the dashboard.
- Never write the JFYI URL or token into repository files. They live in plugin configuration or environment variables only.
