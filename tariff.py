"""TNB domestic tariff (Peninsular Malaysia), RP4 structure effective 1 July 2025.
Review each month: AFA changes monthly. Sources: mytnb.com.my/tariff and TNB press releases."""
from datetime import datetime

LAST_REVIEWED = "21 Oct 2026"
GENERATION = ((1500, 0.2703), (float("inf"), 0.3703))  # RM/kWh, incremental
CAPACITY, NETWORK = 0.0455, 0.1285                      # RM/kWh, every unit
RETAIL = 10.00                                          # RM/month
PROTECTED_KWH = 600   # at or below: no AFA, retail charge or service tax (government extended to 800 kWh; set this
                      # to 800 once the effective date has passed)
KWTBB_RATE, KWTBB_EXEMPT_KWH, SST_RATE = 0.016, 300, 0.08
AFA = {  # RM/kWh by month; later months are forecasts
    "2026-05": 0.0138, "2026-06": 0.0259, "2026-07": 0.0359, "2026-08": 0.0380, "2026-09": 0.0367,
    "2026-10": 0.0336, "2026-11": 0.0281, "2026-12": 0.0548,
}


def afa_rate(when=None):
    key = (when or datetime.now()).strftime("%Y-%m")
    return AFA.get(key, AFA[max(AFA)])
