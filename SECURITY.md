# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report them privately through GitHub: go to the **Security** tab of this repo and click **Report a vulnerability** ([direct link](https://github.com/nicedreamzapp/claude-code-local/security/advisories/new)). Only the maintainer sees the report.

Helpful details: what you found, how to reproduce it, which version or commit, your Mac and macOS version, and the model you were running.

I aim to reply within 3 days and to ship a fix or a clear plan within 30 days, depending on severity. You will be credited in the advisory unless you ask not to be.

## Supported versions

Fixes go into the latest release on `main`. Please update before reporting if you are on an older version.

## What matters most here

The parts where a mistake could hurt someone:

- `install.sh` and `setup.sh`, which people often run with one `curl | bash` line
- the local server in `proxy/`, which only listens on `127.0.0.1` and sits between Claude Code and a model that can edit files and run commands
- model downloads
- the tool call parser that repairs malformed JSON from models
