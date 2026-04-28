# config.py - 应用配置类

import os
from datetime import timedelta

class Config:
    """Flask 应用配置"""

    # 基础配置
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///chat.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # QQ 邮箱 SMTP 配置
    MAIL_SERVER = 'smtp.qq.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')  # QQ 邮箱
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')  # QQ 邮箱授权码（非QQ密码）

    # 邮箱验证开关（关闭后注册只需用户名+密码）
    EMAIL_VERIFICATION_ENABLED = os.getenv('EMAIL_VERIFICATION_ENABLED', 'true').lower() == 'true'

    # 验证码和会话配置
    EMAIL_VERIFICATION_EXPIRES = 600  # 验证码 10 分钟过期
    PASSWORD_RESET_EXPIRES = 3600     # 密码重置 1 小时过期
    SESSION_TOKEN_EXPIRES = 604800    # 会话令牌 7 天过期
