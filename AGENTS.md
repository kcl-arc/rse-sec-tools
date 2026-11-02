# AGENTS

- Favour simplicity in implementation where possible
- Don't add additional dependencies / tools unless they're required
- Ask before adding any new dependencies / tools
- Commit after every block of work or complete task
- When doing manual testing after a task, don't commit until given approval
- Use Conventional Commits format for commit messages
- Sign commits using an SSH key; if the key isn't loaded, ask me to load it for you
- When committing, list the current AI model using format: `Assisted-by: <AGENT_HARNESS>:<MODEL_NAME>`
- Keep READMEs up to date automatically. The main README.md stays short: each tool gets its name and a one-sentence summary only; detailed per-tool docs live in scripts/README.md. Any time a change is made that affects setup steps, make sure both READMEs stay in sync
