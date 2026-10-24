"""
CacheCraft / CacheOpti - Application Entrypoint.

Starts the CacheOpti Performance Studio HTTP server and opens the browser.
Run with:
    python run.py
"""

import sys
import webbrowser
from cacheopti.server import start_server


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    host = "127.0.0.1"

    print("=" * 60)
    print("[*] CacheOpti -- Performance Engineering & Observability Studio")
    print(f"[*] Server running at: http://{host}:{port}")
    print("=" * 60)
    print("Press Ctrl+C to stop the server.")

    server = start_server(host=host, port=port)

    # Automatically launch web browser
    try:
        webbrowser.open(f"http://{host}:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGracefully shutting down CacheOpti...")
        server.shutdown()


if __name__ == "__main__":
    main()
