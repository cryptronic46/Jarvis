from jarvis_web.backend.app import create_app

# Development-only ASGI app. This is the only entry point with Swagger/OpenAPI.
app = create_app(dev_mode=True)
