# edubot/db.py
# додайте / перевірте імпорти:
import os, urllib.parse, ssl
import certifi
import pg8000.native as pg

DATABASE_URL = os.environ.get("DATABASE_URL")  # pooled URI

def _parse_dsn(dsn: str):
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    u = urllib.parse.urlparse(dsn)
    qs = urllib.parse.parse_qs(u.query or "")
    sslmode = (qs.get("sslmode", ["require"])[0]).lower()

    params = {
        "user": urllib.parse.unquote(u.username or ""),
        "password": urllib.parse.unquote(u.password or ""),
        "host": u.hostname or "localhost",
        "port": u.port or 5432,
        "database": (u.path or "/").lstrip("/"),
    }

    # === SSL context ===
    # 1) "verify-full"/"verify-ca": повна перевірка ланцюжка + CA з certifi
    if sslmode in ("verify-full", "verify-ca"):
        ctx = ssl.create_default_context(cafile=certifi.where())
        # check_hostname = True за замовчуванням — залишається
        # verify_mode = CERT_REQUIRED за замовчуванням — залишається

    # 2) "require"/"prefer"/"allow": шифруємо, але без перевірки CA (аналог libpq require)
    elif sslmode in ("require", "prefer", "allow"):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    # 3) "disable" або інше — без TLS (не радимо). Примусимо TLS без перевірки.
    else:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    params["ssl_context"] = ctx
    return params
