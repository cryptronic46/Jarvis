# JARVIS Web

WebJarvis is the browser transport for the main JARVIS runtime.
It is not a separate JARVIS installation and does not own a
separate Core, Brain, Memory, or JarvisApplication.

## Architecture

Production architecture:

Launcher / ProcessHost
  -> build_application()
  -> one JarvisApplication
  -> terminal transport
  -> WebTransportRunner
  -> RealJarvisCoreAdapter
  -> the same JarvisApplication

There must be only one process-wide JARVIS application graph.

The integrated Web implementation lives under:

G:\JARVIS\jarvis_web

## Runtime endpoints

Production WebJarvis:

127.0.0.1:8766

Port 8765 remains reserved for the wallpaper bridge and must not
be reused by WebJarvis.

Vite development mode may use:

127.0.0.1:5173

## Application ownership

build_application() creates the process-wide JarvisApplication.

WebTransportRunner receives that existing application and injects
RealJarvisCoreAdapter(application) into create_app().

The runner owns only the Web transport lifecycle. It must not
construct another JARVIS application graph.

## Local authentication

Browser bootstrap credential generation and distribution belong
to the Launcher / ProcessHost.

Intended authenticated flow:

1. Launcher / ProcessHost generates a short-lived bootstrap token.
2. It passes the token to WebTransportRunner.start().
3. The runner passes the token explicitly to create_app().
4. LocalAuthManager consumes the one-time token.
5. The browser receives the local authenticated session cookie.

WebTransportRunner does not generate bootstrap credentials.

The environment-variable bootstrap path remains only for legacy
separate-process compatibility.

Current limitation:

Running jarvis.py directly starts the integrated Web transport,
but the CLI does not currently generate or distribute a browser
bootstrap token.

Therefore a browser opened directly through the normal CLI path
remains locked until the Launcher / ProcessHost flow is built.

## Security

Production WebJarvis remains localhost-only and retains:

- Host validation and DNS-rebinding protection
- Origin validation
- WebSocket authentication
- local session authentication
- Security Gateway
- Permission Broker
- audit logging
- DPAPI session persistence
- request body limits
- SPA and suspicious-path hardening
- command and Core-introspection firewalls
- panic and revoke controls

Runtime state under jarvis_web/data and jarvis_web/logs must not
be deleted during cleanup, release verification, or update.

## Frontend

Frontend source:

jarvis_web\web\src

Install locked dependencies:

npm --prefix .\jarvis_web\web ci

Build production assets:

npm --prefix .\jarvis_web\web run build

Generated production assets are written to:

jarvis_web\web\dist

Generated bundles must be rebuilt from source. Do not manually
edit minified production assets.

## Tests

Backend, transport, authentication, and security tests live under:

jarvis_web\tests

The Web transport is tested against the existing JarvisApplication
rather than against a separate Web-owned Core.

## Lifecycle direction

The current CLI owns WebTransportRunner after build_application().

The planned Launcher / ProcessHost will later own startup,
readiness, authenticated browser bootstrap, and graceful shutdown.

Changing lifecycle ownership later must not require rewriting
WebTransportRunner or creating a second application graph.
