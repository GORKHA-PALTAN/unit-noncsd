"""Start the Unit Non-CSD App:  python run.py"""
import uvicorn

from app import config

if __name__ == "__main__":
    print(f"Starting {config.APP_NAME}")
    print(f"  On this computer:  http://127.0.0.1:{config.PORT}   (owner dashboard: /admin)")
    if config.HOST not in ("127.0.0.1", "localhost"):
        try:
            from app.routes.admin import _lan_ips
            for ip in _lan_ips():
                print(f"  On phones (same Wi-Fi):  http://{ip}:{config.PORT}")
        except Exception:
            pass
        print("  QR codes for customers and the owner: dashboard > Share & QR codes")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False, proxy_headers=True)
