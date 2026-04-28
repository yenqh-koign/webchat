# auth_routes.py - 认证API路由（注册、登录、密码重置等）

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from models import db, User, EmailVerification, PasswordResetToken, LoginSession
from auth_utils import (
    hash_password, verify_password, generate_verification_code,
    generate_reset_token, generate_session_token
)
from email_utils import send_verification_email, send_password_reset_email

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


@auth_bp.route('/config', methods=['GET'])
def get_auth_config():
    """返回前端所需的认证配置"""
    return jsonify({
        'email_verification_enabled': current_app.config.get('EMAIL_VERIFICATION_ENABLED', True)
    })


@auth_bp.route('/send-verification-code', methods=['POST'])
def send_verification_code():
    """发送邮箱验证码"""
    email = request.json.get('email')

    # 验证邮箱格式
    if not email or '@' not in email:
        return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

    # 检查邮箱是否已注册
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': '该邮箱已被注册'}), 400

    # 生成验证码
    code = generate_verification_code()
    expires_at = datetime.now() + timedelta(seconds=600)  # 10分钟

    # 保存验证码
    verification = EmailVerification(
        email=email,
        code=code,
        purpose='register',
        expires_at=expires_at
    )
    db.session.add(verification)
    db.session.commit()

    # 发送邮件
    if send_verification_email(email, code):
        return jsonify({'success': True, 'message': '验证码已发送至您的邮箱'})
    else:
        return jsonify({'success': False, 'message': '邮件发送失败，请检查邮箱配置'}), 500


@auth_bp.route('/register', methods=['POST'])
def register():
    """注册新用户"""
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    email_verification = current_app.config.get('EMAIL_VERIFICATION_ENABLED', True)

    # 验证输入
    if not username or len(username) < 1 or len(username) > 20:
        return jsonify({'success': False, 'message': '用户名长度必须在 1-20 字符之间'}), 400

    if not password or len(password) < 8:
        return jsonify({'success': False, 'message': '密码长度至少为 8 位'}), 400

    # 检查用户名是否已存在
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'message': '用户名已存在'}), 400

    if email_verification:
        # 启用邮箱验证：需要邮箱和验证码
        email = data.get('email', '').strip()
        code = data.get('code', '').strip()

        if not email or '@' not in email:
            return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

        if User.query.filter_by(email=email).first():
            return jsonify({'success': False, 'message': '该邮箱已被注册'}), 400

        verification = EmailVerification.query.filter_by(
            email=email,
            code=code,
            purpose='register',
            is_used=False
        ).filter(EmailVerification.expires_at > datetime.now()).first()

        if not verification:
            return jsonify({'success': False, 'message': '验证码无效或已过期'}), 400

        user = User(
            username=username,
            email=email,
            user_type='registered',
            password_hash=hash_password(password),
            email_verified=True,
            registered_at=datetime.now()
        )
        db.session.add(user)
        verification.is_used = True
    else:
        # 关闭邮箱验证：只需用户名+密码
        email = data.get('email', '').strip() or None
        user = User(
            username=username,
            email=email,
            user_type='registered',
            password_hash=hash_password(password),
            email_verified=False,
            registered_at=datetime.now()
        )
        db.session.add(user)

    db.session.commit()
    return jsonify({'success': True, 'message': '注册成功！'})


@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录"""
    username = request.json.get('username', '').strip()
    password = request.json.get('password', '')
    remember_me = request.json.get('remember_me', False)

    # 查找用户
    user = User.query.filter_by(username=username, user_type='registered').first()

    if not user or not verify_password(password, user.password_hash):
        return jsonify({'success': False, 'message': '用户名或密码错误'}), 401

    # 更新最后登录时间
    user.last_seen = datetime.now()

    # 生成会话令牌（如果勾选"记住我"）
    session_token = None
    if remember_me:
        session_token = generate_session_token()
        session = LoginSession(
            user_id=user.id,
            session_token=session_token,
            expires_at=datetime.now() + timedelta(seconds=604800),  # 7天
            user_agent=request.headers.get('User-Agent'),
            ip_address=request.remote_addr
        )
        db.session.add(session)

    db.session.commit()

    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'session_token': session_token
    })


@auth_bp.route('/guest-login', methods=['POST'])
def guest_login():
    """访客登录"""
    username = request.json.get('username', '').strip()

    # 验证用户名
    if not username or len(username) < 1 or len(username) > 20:
        return jsonify({'success': False, 'message': '用户名长度必须在 1-20 字符之间'}), 400

    # 检查是否是已注册用户
    existing_user = User.query.filter_by(username=username).first()
    if existing_user and existing_user.user_type == 'registered':
        return jsonify({
            'success': False,
            'message': '该用户名已被注册，请使用密码登录',
            'require_password': True
        }), 400

    # 创建或查找访客用户
    user = existing_user or User(username=username, user_type='guest')
    if not existing_user:
        db.session.add(user)
    else:
        user.last_seen = datetime.now()

    db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict()})


@auth_bp.route('/auto-login', methods=['POST'])
def auto_login():
    """自动登录（使用会话令牌）"""
    session_token = request.json.get('session_token')

    if not session_token:
        return jsonify({'success': False, 'message': '缺少会话令牌'}), 400

    # 查找有效的会话
    session = LoginSession.query.filter_by(
        session_token=session_token
    ).filter(LoginSession.expires_at > datetime.now()).first()

    if not session:
        return jsonify({'success': False, 'message': '会话已过期或无效'}), 401

    # 更新会话使用时间
    session.last_used_at = datetime.now()
    session.user.last_seen = datetime.now()
    db.session.commit()

    return jsonify({
        'success': True,
        'user': session.user.to_dict()
    })


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """申请密码重置"""
    email = request.json.get('email', '').strip()

    # 查找用户（不透露用户是否存在）
    user = User.query.filter_by(email=email, user_type='registered').first()

    if user:
        # 生成重置令牌
        token = generate_reset_token()
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.now() + timedelta(seconds=3600)  # 1小时
        )
        db.session.add(reset_token)
        db.session.commit()

        # 发送重置邮件
        reset_link = f"http://localhost:3000/reset-password?token={token}"
        send_password_reset_email(email, reset_link)

    # 无论用户是否存在，都返回成功（防止邮箱枚举）
    return jsonify({'success': True, 'message': '如果该邮箱已注册，重置链接已发送'})


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """重置密码"""
    token = request.json.get('token')
    new_password = request.json.get('password')

    if not new_password or len(new_password) < 8:
        return jsonify({'success': False, 'message': '密码长度至少为 8 位'}), 400

    # 验证令牌
    reset_token = PasswordResetToken.query.filter_by(
        token=token,
        is_used=False
    ).filter(PasswordResetToken.expires_at > datetime.now()).first()

    if not reset_token:
        return jsonify({'success': False, 'message': '重置链接无效或已过期'}), 400

    # 更新密码
    reset_token.user.password_hash = hash_password(new_password)
    reset_token.is_used = True
    db.session.commit()

    return jsonify({'success': True, 'message': '密码重置成功！'})
