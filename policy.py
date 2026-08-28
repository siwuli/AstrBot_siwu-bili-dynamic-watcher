"""轮询策略（纯标准库，可独立测试）。

自适应退避：实际间隔 = min(基础间隔 × 2^退避级别, 上限)；再叠加随机抖动，
避免固定节奏被风控识别。连续失败/触发风控时退避级别 +1，成功后归零。
"""

import random

MIN_INTERVAL = 10


def effective_interval(base, level, cap=3600):
    """退避后的基准间隔（不含抖动）。"""
    base = max(MIN_INTERVAL, int(base or MIN_INTERVAL))
    cap = max(base, int(cap or base))
    return min(base * (2 ** max(0, int(level or 0))), cap)


def jittered_interval(base, level, cap=3600):
    """带随机抖动的实际睡眠秒数（0~20% 上浮）。"""
    iv = float(effective_interval(base, level, cap))
    return iv + random.uniform(0, max(2.0, iv * 0.2))


def next_backoff_level(current, cap_level=7):
    """连续失败/风控触发时退避级别 +1（封顶 cap_level）。"""
    return min(cap_level, max(0, int(current)) + 1)


def reset_backoff_level():
    """请求成功时退避归零。"""
    return 0
