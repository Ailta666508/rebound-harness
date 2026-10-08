# Security boundaries

Rebound 0.1 is for a trusted workstation and controlled experiments. The local
inspector has no multi-user authentication and binds to loopback. Do not expose
it through a public reverse proxy. The HTTP benchmark fixture is a test service,
not a production tool server.

Local file tools validate paths and reject symlinks, but do not provide operating
system isolation against another process changing those paths. Stdio MCP servers
are explicitly trusted local executables. Tool-provided evidence is trusted at
the adapter boundary; the runtime cannot authenticate arbitrary real-world claims.

The optional Docker tool has no host mounts or network, runs as an unprivileged
user with resource limits, and explicitly removes its container on cleanup. It
depends on the Docker daemon and is not a claim that container isolation defeats
every malicious program. A host process killed before cleanup may leave a named
`rebound-*` container; operators should inspect and remove abandoned containers.

Do not commit API keys, private prompts, or real user traces. Runtime logs exclude
model authorization headers, but tool arguments/results and conversation contents
are intentionally persisted as task data.

Report a vulnerability using GitHub's private vulnerability reporting when
available; otherwise open an issue asking for a private contact without including
exploit details or credentials.
