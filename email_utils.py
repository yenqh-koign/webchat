# email_utils.py - SMTP 邮件发送工具

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app


def send_verification_email(email, code):
    """发送注册验证码邮件"""
    subject = "聊天室注册验证码"
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2196F3;">欢迎注册聊天室！</h2>
        <p>您的邮箱验证码为：</p>
        <div style="font-size: 32px; font-weight: bold; color: #2196F3;
                    letter-spacing: 5px; text-align: center; padding: 20px;
                    background: #f5f5f5; border-radius: 8px; margin: 20px 0;">
            {code}
        </div>
        <p style="color: #f44336;">验证码将在 <strong>10 分钟</strong> 后失效，请尽快使用。</p>
        <p style="color: #999; font-size: 12px; margin-top: 30px;">
            如果这不是您本人的操作，请忽略此邮件。
        </p>
    </div>
    """
    return _send_email(email, subject, html_content)


def send_password_reset_email(email, reset_link):
    """发送密码重置邮件"""
    subject = "聊天室密码重置"
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2196F3;">密码重置请求</h2>
        <p>您正在重置聊天室账户的密码。</p>
        <p>请点击下方按钮重置密码：</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_link}" style="display: inline-block; padding: 12px 30px;
               background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%);
               color: white; text-decoration: none; border-radius: 8px; font-weight: bold;">
                重置密码
            </a>
        </div>
        <p style="color: #999; font-size: 14px;">
            或复制此链接到浏览器：<br>
            <a href="{reset_link}" style="color: #2196F3; word-break: break-all;">{reset_link}</a>
        </p>
        <p style="color: #f44336; margin-top: 20px;">
            此链接将在 <strong>1 小时</strong> 后失效。
        </p>
        <p style="color: #999; font-size: 12px; margin-top: 30px;">
            如果这不是您本人的操作，请忽略此邮件，您的密码不会被更改。
        </p>
    </div>
    """
    return _send_email(email, subject, html_content)


def _send_email(to_email, subject, html_content):
    """通用邮件发送函数（SMTP）"""
    try:
        # 获取配置
        mail_username = current_app.config['MAIL_USERNAME']
        mail_password = current_app.config['MAIL_PASSWORD']

        print(f"[邮件] 准备发送邮件到: {to_email}")
        print(f"[邮件] 发件人: {mail_username}")
        print(f"[邮件] 授权码长度: {len(mail_password) if mail_password else 0}")

        # 构造邮件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = mail_username
        msg['To'] = to_email

        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)

        # 使用 SSL 连接 QQ 邮箱（端口 465）
        print("[邮件] 正在连接 smtp.qq.com:465 ...")
        server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30)
        server.set_debuglevel(1)  # 启用调试输出

        print("[邮件] 连接成功，正在登录...")
        server.login(mail_username, mail_password)

        print("[邮件] 登录成功，正在发送...")
        server.send_message(msg)
        server.quit()

        print(f"[邮件] 邮件已成功发送至 {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"[邮件] 认证失败 - 请检查邮箱和授权码: {e}")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"[邮件] 连接失败: {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"[邮件] SMTP错误: {e}")
        return False
    except Exception as e:
        print(f"[邮件] 发送失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
