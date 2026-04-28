# auth_utils.py - 密码加密和令牌生成工具

import bcrypt
import secrets
import random
import string
from datetime import datetime, timedelta


def hash_password(password):
    """生成密码哈希（bcrypt 自动加盐）"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, password_hash):
    """验证密码"""
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


def generate_verification_code():
    """生成6位数字验证码"""
    return ''.join(random.choices(string.digits, k=6))


def generate_reset_token():
    """生成密码重置令牌（32字节安全随机字符串）"""
    return secrets.token_urlsafe(32)


def generate_session_token():
    """生成会话令牌（32字节安全随机字符串）"""
    return secrets.token_urlsafe(32)
