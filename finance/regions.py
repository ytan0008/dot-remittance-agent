"""APEC economies and payment routes. Region settings never imply nationality or transfer eligibility."""

# code: (currency, languages, time zones). Display names are localized by the browser (Intl.DisplayNames).
ECONOMIES = {
    "AU": ("AUD", ["en"], ["Australia/Sydney", "Australia/Perth"]),
    "BN": ("BND", ["ms", "en"], ["Asia/Brunei"]),
    "CA": ("CAD", ["en", "fr"], ["America/Toronto", "America/Vancouver"]),
    "CL": ("CLP", ["es"], ["America/Santiago"]),
    "CN": ("CNY", ["zh-CN"], ["Asia/Shanghai"]),
    "HK": ("HKD", ["zh-TW", "en"], ["Asia/Hong_Kong"]),
    "ID": ("IDR", ["id"], ["Asia/Jakarta"]),
    "JP": ("JPY", ["ja"], ["Asia/Tokyo"]),
    "KR": ("KRW", ["ko"], ["Asia/Seoul"]),
    "MY": ("MYR", ["ms", "en"], ["Asia/Kuala_Lumpur"]),
    "MX": ("MXN", ["es"], ["America/Mexico_City"]),
    "NZ": ("NZD", ["en"], ["Pacific/Auckland"]),
    "PG": ("PGK", ["en"], ["Pacific/Port_Moresby"]),
    "PE": ("PEN", ["es"], ["America/Lima"]),
    "PH": ("PHP", ["en", "fil"], ["Asia/Manila"]),
    "RU": ("RUB", ["ru"], ["Europe/Moscow"]),
    "SG": ("SGD", ["en", "zh-CN", "ms"], ["Asia/Singapore"]),
    "TW": ("TWD", ["zh-TW"], ["Asia/Taipei"]),
    "TH": ("THB", ["th"], ["Asia/Bangkok"]),
    "US": ("USD", ["en"], ["America/New_York", "America/Los_Angeles"]),
    "VN": ("VND", ["vi"], ["Asia/Ho_Chi_Minh"]),
}

# (send, receive, payments enabled by default). Enabling a route never bypasses provider support.
SEED_ROUTES = [
    ("AU", "CN", True), ("AU", "VN", True), ("US", "PH", True), ("US", "CN", False), ("US", "VN", False),
    ("US", "MX", False), ("AU", "PH", False), ("AU", "NZ", False), ("JP", "VN", False), ("KR", "VN", False),
    ("SG", "MY", False), ("CA", "CN", False), ("HK", "CN", False), ("AU", "TW", False),
    ("CN", "AU", True), ("CN", "US", False), ("CN", "VN", False),
]


def economy(code):
    if code not in ECONOMIES:
        from .domain import Denied
        raise Denied("unknown economy", "economy_unknown")
    currency, languages, zones = ECONOMIES[code]
    return dict(code=code, currency=currency, languages=languages, time_zones=zones)


def route_body(send, receive):
    a, b = economy(send), economy(receive)
    return dict(id=f"{send}-{receive}", send=send, receive=receive, source=a["currency"], target=b["currency"],
                time_zones=dict(send=a["time_zones"][0], receive=b["time_zones"][0]))
