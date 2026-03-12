# server_timezone.py
"""
时区处理工具 - 统一管理北京时间转换
所有时间都以北京时间（UTC+8）存储和显示
"""

from datetime import datetime, timedelta
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

# 北京时间偏移量（小时）
BEIJING_OFFSET = 8


def get_beijing_now() -> datetime:
    """
    获取当前北京时间

    Returns:
        datetime: 当前北京时间（无时区信息的datetime对象）
    """
    return datetime.utcnow() + timedelta(hours=BEIJING_OFFSET)


def to_beijing_time(dt: Optional[datetime]) -> Optional[datetime]:
    """
    将任意时间转换为北京时间

    Args:
        dt: 输入的时间（可以是UTC时间或其他）

    Returns:
        转换后的北京时间，如果输入为None则返回None
    """
    if dt is None:
        return None

    # 移除可能的时区信息，确保是naive datetime
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)

    return dt + timedelta(hours=BEIJING_OFFSET)


def from_beijing_to_utc(dt: datetime) -> datetime:
    """
    将北京时间转换为UTC时间（用于查询时可能需要）

    Args:
        dt: 北京时间

    Returns:
        UTC时间
    """
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt - timedelta(hours=BEIJING_OFFSET)


def format_beijing_time(
    dt: Optional[datetime], format_str: str = "%Y-%m-%d %H:%M:%S"
) -> Optional[str]:
    """
    格式化北京时间为字符串

    Args:
        dt: 要格式化的时间
        format_str: 格式化字符串

    Returns:
        格式化后的时间字符串
    """
    if dt is None:
        return None
    beijing_time = to_beijing_time(dt)
    return beijing_time.strftime(format_str)


def get_date_range_for_day(target_date: Optional[datetime] = None):
    """
    获取指定日期的开始和结束时间（北京时间）

    Args:
        target_date: 目标日期，如果为None则使用今天

    Returns:
        tuple: (开始时间, 结束时间)
    """
    if target_date is None:
        target_date = get_beijing_now()

    # 确保是date对象
    if isinstance(target_date, datetime):
        date_obj = target_date.date()
    else:
        date_obj = target_date

    start_time = datetime.combine(date_obj, datetime.min.time())
    end_time = start_time + timedelta(days=1)

    return start_time, end_time


def parse_beijing_datetime(datetime_str: str) -> Optional[datetime]:
    """
    解析北京时间字符串

    Args:
        datetime_str: 时间字符串，格式如 "2026-03-12 13:30:00"

    Returns:
        datetime对象
    """
    try:
        return datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                return datetime.strptime(datetime_str, "%Y-%m-%d")
            except ValueError:
                logger.error(f"无法解析时间字符串: {datetime_str}")
                return None


def validate_beijing_time(dt: datetime) -> bool:
    """
    验证时间是否为有效的北京时间

    Args:
        dt: 要验证的时间

    Returns:
        bool: 是否有效
    """
    if dt is None:
        return False

    # 检查年份范围（可以根据需要调整）
    if dt.year < 2000 or dt.year > 2100:
        return False

    return True


# 为了方便，直接导出常用函数
__all__ = [
    "get_beijing_now",
    "to_beijing_time",
    "from_beijing_to_utc",
    "format_beijing_time",
    "get_date_range_for_day",
    "parse_beijing_datetime",
    "validate_beijing_time",
]
