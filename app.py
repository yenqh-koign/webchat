# app.py - 聊天应用主程序
# 集成 SQLite 数据库、私聊功能、消息通知、图片优化

import engineio.async_drivers.threading
from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from sqlalchemy import or_, and_
import uuid
import os
import sys
from datetime import datetime

# --- 获取应用运行目录（exe 同级目录）---
def get_app_dir():
    """获取应用程序所在目录（支持 PyInstaller 打包）"""
    if getattr(sys, 'frozen', False):
        # 打包后的 exe 运行
        return os.path.dirname(sys.executable)
    else:
        # 开发环境直接运行
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()

# 必须在导入 Config 之前加载 .env 文件！
# 从 exe 同级目录加载 .env 文件
from dotenv import load_dotenv
env_path = os.path.join(APP_DIR, '.env')
load_dotenv(env_path)

from models import db, User, Message, Group, GroupMember, GroupMessage, PrivateMessage, PrivateContact, LoginSession
from image_utils import process_uploaded_image
from config import Config
from auth_routes import auth_bp

UPLOAD_FOLDER = os.path.join(APP_DIR, 'uploads')
THUMBNAIL_FOLDER = os.path.join(UPLOAD_FOLDER, 'thumbnails')

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

# --- App 初始化 ---
app = Flask(__name__, static_folder='static', static_url_path='/static')

# 从 Config 类加载配置
app.config.from_object(Config)
# 保持原有的数据库路径（exe 同级目录）
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(APP_DIR, "chat.db")}'

# 初始化扩展
db.init_app(app)
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", max_http_buffer_size=10 * 1024 * 1024, async_mode='threading')

# 注册认证路由
app.register_blueprint(auth_bp)

# --- 内存缓存（在线用户映射） ---
sids_to_usernames = {}  # {sid: username}
usernames_to_sids = {}  # {username: sid}
sids_to_user_ids = {}   # {sid: user_id}


# --- 辅助函数 ---
def get_current_user():
    """获取当前连接的用户"""
    user_id = sids_to_user_ids.get(request.sid)
    if user_id:
        return db.session.get(User, user_id)
    return None


def validate_username(username):
    """验证用户名是否合法"""
    if not username:
        return False, "用户名不能为空"

    # 去除首尾空格
    username = username.strip()

    if len(username) < 1:
        return False, "用户名不能为空"

    if len(username) > 20:
        return False, "用户名不能超过20个字符"

    # 检查是否包含危险字符（HTML标签等）
    dangerous_chars = ['<', '>', '&', '"', "'", '/', '\\', '\n', '\r', '\t']
    for char in dangerous_chars:
        if char in username:
            return False, "用户名包含非法字符"

    # 检查是否全是空格
    if not username.strip():
        return False, "用户名不能全是空格"

    return True, username.strip()


def get_private_room_name(user1_id, user2_id):
    """生成私聊房间名"""
    ids = sorted([user1_id, user2_id])
    return f"private-{ids[0]}-{ids[1]}"


def get_unread_counts(user_id):
    """获取用户的未读消息计数"""
    private_unread = db.session.query(
        PrivateMessage.sender_id,
        db.func.count(PrivateMessage.id).label('count')
    ).filter(
        PrivateMessage.receiver_id == user_id,
        PrivateMessage.read == False
    ).group_by(PrivateMessage.sender_id).all()

    return {
        'private': {str(sender_id): count for sender_id, count in private_unread}
    }


# --- HTTP 路由 ---
@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供上传文件的访问（从 exe 同级 uploads 目录）"""
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/upload', methods=['POST'])
def upload_file():
    """处理文件上传 - 增加图片压缩和缩略图生成"""
    if 'file' not in request.files:
        return {'error': '没有文件'}, 400

    file = request.files['file']
    if file.filename == '':
        return {'error': '未选择文件'}, 400

    # 检查文件类型
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    file_ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''

    if file_ext not in allowed_extensions:
        return {'error': '不支持的文件类型'}, 400

    # 检查文件大小（10MB 限制）
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > 10 * 1024 * 1024:
        return {'error': '文件大小超过 10MB 限制'}, 400

    # 处理图片 - 使用 exe 同级的 uploads 目录
    result = process_uploaded_image(file, UPLOAD_FOLDER)

    if result['success']:
        return {
            'url': result['original'],
            'thumbnail': result['thumbnail']
        }
    else:
        return {'error': result.get('error', '图片处理失败')}, 500


# --- Socket.IO 事件处理 ---
@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print(f"客户端连接: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    username = sids_to_usernames.pop(request.sid, None)
    if username:
        usernames_to_sids.pop(username, None)
        sids_to_user_ids.pop(request.sid, None)
        print(f"客户端 {username} ({request.sid}) 断开连接")
        emit('user list', list(usernames_to_sids.keys()), broadcast=True)


@socketio.on('login')
def handle_login(data):
    """用户登录（支持访客和注册用户双模式）"""
    # 检查会话令牌（自动登录）
    session_token = data.get('session_token')
    if session_token:
        session = LoginSession.query.filter_by(
            session_token=session_token
        ).filter(LoginSession.expires_at > datetime.now()).first()

        if session:
            user = session.user
            user.last_seen = datetime.now()
            session.last_used_at = datetime.now()
            db.session.commit()

            # 设置用户会话
            sids_to_usernames[request.sid] = user.username
            usernames_to_sids[user.username] = request.sid
            sids_to_user_ids[request.sid] = user.id

            # 发送登录成功
            emit('login success', {'username': user.username}, room=request.sid)

            # 发送公共聊天历史
            messages = Message.query.order_by(Message.created_at.desc()).limit(100).all()
            messages.reverse()
            emit('chat history', [msg.to_dict() for msg in messages], room=request.sid)

            # 广播在线用户列表
            emit('user list', list(usernames_to_sids.keys()), broadcast=True)

            # 发送用户的群组列表
            user_groups = Group.query.join(GroupMember).filter(
                GroupMember.user_id == user.id
            ).all()
            if user_groups:
                emit('my groups', [g.name for g in user_groups], room=request.sid)
                for group in user_groups:
                    room_name = f"group-{group.name}"
                    join_room(room_name)
                    group_msgs = GroupMessage.query.filter_by(
                        group_id=group.id
                    ).order_by(GroupMessage.created_at.desc()).limit(100).all()
                    group_msgs.reverse()
                    emit('group history', {
                        'room': room_name,
                        'history': [msg.to_dict() for msg in group_msgs]
                    }, room=request.sid)

            # 发送未读消息计数
            emit('unread counts', get_unread_counts(user.id), room=request.sid)

            # 发送私聊联系人列表
            contacts = PrivateContact.query.filter_by(user_id=user.id).all()
            contact_list = [c.contact.to_dict() for c in contacts if c.contact]
            emit('private contacts', contact_list, room=request.sid)

            # 发送用户偏好设置
            emit('preferences updated', user.to_dict(), room=request.sid)
            return

    # 访客登录（原有逻辑）
    username = data.get('username')

    # 验证用户名
    is_valid, result = validate_username(username)
    if not is_valid:
        emit('login error', {'message': result}, room=request.sid)
        return

    username = result  # 使用清理后的用户名

    # 查找用户
    user = User.query.filter_by(username=username).first()

    # 如果是注册用户，要求密码登录
    if user and user.user_type == 'registered':
        emit('login error', {
            'message': '该用户名已被注册，请使用密码登录',
            'require_password': True
        }, room=request.sid)
        return

    # 创建或更新访客用户
    if not user:
        user = User(username=username, user_type='guest')
        db.session.add(user)
        db.session.commit()
    else:
        user.last_seen = datetime.now()
        db.session.commit()

    # 更新内存映射
    sids_to_usernames[request.sid] = username
    usernames_to_sids[username] = request.sid
    sids_to_user_ids[request.sid] = user.id

    # 发送公共聊天历史（最近100条）
    messages = Message.query.order_by(Message.created_at.desc()).limit(100).all()
    messages.reverse()
    emit('chat history', [msg.to_dict() for msg in messages], room=request.sid)

    # 广播在线用户列表
    emit('user list', list(usernames_to_sids.keys()), broadcast=True)

    # 发送用户的群组列表
    user_groups = Group.query.join(GroupMember).filter(
        GroupMember.user_id == user.id
    ).all()
    if user_groups:
        emit('my groups', [g.name for g in user_groups], room=request.sid)
        for group in user_groups:
            room_name = f"group-{group.name}"
            join_room(room_name)
            group_msgs = GroupMessage.query.filter_by(
                group_id=group.id
            ).order_by(GroupMessage.created_at.desc()).limit(100).all()
            group_msgs.reverse()
            emit('group history', {
                'room': room_name,
                'history': [msg.to_dict() for msg in group_msgs]
            }, room=request.sid)

    # 发送未读消息计数
    emit('unread counts', get_unread_counts(user.id), room=request.sid)

    # 发送私聊联系人列表
    contacts = PrivateContact.query.filter_by(user_id=user.id).all()
    contact_list = [c.contact.to_dict() for c in contacts if c.contact]
    emit('private contacts', contact_list, room=request.sid)

    # 发送用户偏好设置
    emit('preferences updated', user.to_dict(), room=request.sid)


@socketio.on('chat message')
def handle_chat_message(data):
    """公共聊天消息"""
    user = get_current_user()
    if not user:
        return

    message_id = str(uuid.uuid4())

    # 处理回复
    reply_to_id = None
    if data.get('replyTo') and data['replyTo'].get('id'):
        reply_to_id = data['replyTo']['id']

    # 处理图片
    image_url = data.get('image')
    thumbnail_url = data.get('thumbnail')

    # 创建消息记录
    new_message = Message(
        id=message_id,
        text=data.get('text'),
        image=image_url,
        thumbnail=thumbnail_url,
        sender_id=user.id,
        reply_to_id=reply_to_id
    )
    db.session.add(new_message)
    db.session.commit()

    emit('chat message', new_message.to_dict(), broadcast=True)


# --- 私聊功能 ---
@socketio.on('start private chat')
def handle_start_private_chat(data):
    """开启私聊会话 - 支持与离线用户私聊"""
    user = get_current_user()
    target_username = data.get('username')

    if not user or not target_username:
        return

    # 查找目标用户，如果不存在则创建
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        # 创建新用户记录（允许与未注册用户私聊）
        target_user = User(username=target_username)
        db.session.add(target_user)
        db.session.commit()

    if target_user.id == user.id:
        emit('error', {'message': '不能与自己私聊'}, room=request.sid)
        return

    room_name = get_private_room_name(user.id, target_user.id)
    join_room(room_name)

    # 加载私聊历史（最近100条）
    history = PrivateMessage.query.filter(
        or_(
            and_(PrivateMessage.sender_id == user.id,
                 PrivateMessage.receiver_id == target_user.id),
            and_(PrivateMessage.sender_id == target_user.id,
                 PrivateMessage.receiver_id == user.id)
        )
    ).order_by(PrivateMessage.created_at.desc()).limit(100).all()
    history.reverse()

    # 标记收到的消息为已读
    PrivateMessage.query.filter(
        PrivateMessage.sender_id == target_user.id,
        PrivateMessage.receiver_id == user.id,
        PrivateMessage.read == False
    ).update({'read': True})
    db.session.commit()

    emit('private chat started', {
        'room': room_name,
        'target_user': target_user.to_dict(),
        'history': [msg.to_dict() for msg in history]
    }, room=request.sid)

    emit('unread counts', get_unread_counts(user.id), room=request.sid)


@socketio.on('private message')
def handle_private_message(data):
    """私聊消息"""
    user = get_current_user()
    room = data.get('room')

    if not user or not room:
        return

    # 从房间名解析目标用户ID
    parts = room.split('-')
    if len(parts) != 3 or parts[0] != 'private':
        return

    try:
        user_ids = [int(parts[1]), int(parts[2])]
    except ValueError:
        emit('error', {'message': '无效的房间名'}, room=request.sid)
        return

    target_user_id = user_ids[0] if user_ids[1] == user.id else user_ids[1]

    target_user = db.session.get(User, target_user_id)
    if not target_user:
        return

    message_id = str(uuid.uuid4())

    reply_to_id = None
    if data.get('replyTo') and data['replyTo'].get('id'):
        reply_to_id = data['replyTo']['id']

    image_url = data.get('image')
    thumbnail_url = data.get('thumbnail')

    new_message = PrivateMessage(
        id=message_id,
        sender_id=user.id,
        receiver_id=target_user_id,
        text=data.get('text'),
        image=image_url,
        thumbnail=thumbnail_url,
        reply_to_id=reply_to_id,
        read=False
    )
    db.session.add(new_message)

    # 自动为接收者添加发送者为联系人（如果还没有）
    existing_contact = PrivateContact.query.filter_by(
        user_id=target_user_id, contact_id=user.id
    ).first()
    if not existing_contact:
        new_contact = PrivateContact(user_id=target_user_id, contact_id=user.id)
        db.session.add(new_contact)

    db.session.commit()

    emit('private message', new_message.to_dict(), room=room)

    # 如果目标用户在线，发送通知并更新联系人列表
    target_sid = usernames_to_sids.get(target_user.username)
    if target_sid:
        # 通知接收者添加联系人到私聊列表
        if not existing_contact:
            emit('private contact added', user.to_dict(), room=target_sid)

        emit('new message notification', {
            'type': 'private',
            'from_user': user.username,
            'from_user_id': user.id,
            'preview': data.get('text', '[图片]')[:50] if data.get('text') else '[图片]',
            'room': room
        }, room=target_sid)
        emit('unread counts', get_unread_counts(target_user_id), room=target_sid)


@socketio.on('mark messages read')
def handle_mark_messages_read(data):
    """标记消息为已读"""
    user = get_current_user()
    room = data.get('room')

    if not user or not room:
        return

    if room.startswith('private-'):
        parts = room.split('-')
        if len(parts) != 3:
            return

        try:
            user_ids = [int(parts[1]), int(parts[2])]
        except ValueError:
            return

        other_user_id = user_ids[0] if user_ids[1] == user.id else user_ids[1]

        PrivateMessage.query.filter(
            PrivateMessage.sender_id == other_user_id,
            PrivateMessage.receiver_id == user.id,
            PrivateMessage.read == False
        ).update({'read': True})
        db.session.commit()

        other_user = db.session.get(User, other_user_id)
        if other_user:
            other_sid = usernames_to_sids.get(other_user.username)
            if other_sid:
                emit('messages read', {'room': room, 'reader': user.username}, room=other_sid)

    emit('unread counts', get_unread_counts(user.id), room=request.sid)


# --- 群组功能 ---
@socketio.on('create group')
def handle_create_group(data):
    """创建或加入群组 - 如果群组已存在则加入，否则创建"""
    user = get_current_user()
    group_name = data.get('group_name')

    if not user or not group_name:
        return

    existing_group = Group.query.filter_by(name=group_name).first()

    if existing_group:
        # 群组已存在，尝试加入
        existing_member = GroupMember.query.filter_by(
            group_id=existing_group.id, user_id=user.id
        ).first()

        if not existing_member:
            # 用户不是成员，添加为成员
            member = GroupMember(group_id=existing_group.id, user_id=user.id)
            db.session.add(member)
            db.session.commit()

        room_name = f"group-{group_name}"
        join_room(room_name)

        # 加载群聊历史
        group_msgs = GroupMessage.query.filter_by(
            group_id=existing_group.id
        ).order_by(GroupMessage.created_at.desc()).limit(100).all()
        group_msgs.reverse()

        emit('group history', {
            'room': room_name,
            'history': [msg.to_dict() for msg in group_msgs]
        }, room=request.sid)

        emit('group joined', {'name': group_name, 'room': room_name}, room=request.sid)
        return

    # 群组不存在，创建新群组
    group = Group(name=group_name, owner_id=user.id)
    db.session.add(group)
    db.session.commit()

    member = GroupMember(group_id=group.id, user_id=user.id)
    db.session.add(member)
    db.session.commit()

    room_name = f"group-{group_name}"
    join_room(room_name)

    emit('group created', {'name': group_name, 'room': room_name}, room=request.sid)


@socketio.on('join group')
def handle_join_group(data):
    """加入群组"""
    user = get_current_user()
    group_name = data.get('group_name')

    if not user or not group_name:
        return

    group = Group.query.filter_by(name=group_name).first()
    if not group:
        emit('error', {'message': '群组不存在'}, room=request.sid)
        return

    existing_member = GroupMember.query.filter_by(
        group_id=group.id, user_id=user.id
    ).first()

    if not existing_member:
        member = GroupMember(group_id=group.id, user_id=user.id)
        db.session.add(member)
        db.session.commit()

    room_name = f"group-{group_name}"
    join_room(room_name)

    group_msgs = GroupMessage.query.filter_by(
        group_id=group.id
    ).order_by(GroupMessage.created_at.desc()).limit(100).all()
    group_msgs.reverse()

    emit('group history', {
        'room': room_name,
        'history': [msg.to_dict() for msg in group_msgs]
    }, room=request.sid)

    emit('group joined', {'name': group_name, 'room': room_name}, room=request.sid)


@socketio.on('group message')
def handle_group_message(data):
    """群组消息"""
    user = get_current_user()
    room = data.get('room')

    if not user or not room:
        return

    group_name = room.replace('group-', '')
    group = Group.query.filter_by(name=group_name).first()

    if not group:
        return

    is_member = GroupMember.query.filter_by(
        group_id=group.id, user_id=user.id
    ).first()

    if not is_member:
        emit('error', {'message': '您不是该群组成员'}, room=request.sid)
        return

    message_id = str(uuid.uuid4())

    reply_to_id = None
    if data.get('replyTo') and data['replyTo'].get('id'):
        reply_to_id = data['replyTo']['id']

    image_url = data.get('image')
    thumbnail_url = data.get('thumbnail')

    new_message = GroupMessage(
        id=message_id,
        group_id=group.id,
        text=data.get('text'),
        image=image_url,
        thumbnail=thumbnail_url,
        sender_id=user.id,
        reply_to_id=reply_to_id
    )
    db.session.add(new_message)
    db.session.commit()

    emit('group message', new_message.to_dict(), room=room)

    # 向不在当前房间的群成员发送通知
    for member in group.members:
        if member.user_id != user.id:
            member_user = db.session.get(User, member.user_id)
            if member_user:
                member_sid = usernames_to_sids.get(member_user.username)
                if member_sid:
                    emit('new message notification', {
                        'type': 'group',
                        'group_name': group.name,
                        'from_user': user.username,
                        'preview': data.get('text', '[图片]')[:50] if data.get('text') else '[图片]',
                        'room': room
                    }, room=member_sid)


@socketio.on('leave group')
def handle_leave_group(data):
    """离开群组"""
    user = get_current_user()
    group_name = data.get('group_name')
    delete_history = data.get('delete_history', False)  # 是否删除历史记录

    if not user or not group_name:
        return

    group = Group.query.filter_by(name=group_name).first()
    if not group:
        return

    member = GroupMember.query.filter_by(
        group_id=group.id, user_id=user.id
    ).first()

    if member:
        db.session.delete(member)
        db.session.commit()

        room_name = f"group-{group_name}"
        leave_room(room_name)

        # 如果群组为空
        if group.members.count() == 0:
            if delete_history:
                # 删除所有群聊消息和群组本身
                GroupMessage.query.filter_by(group_id=group.id).delete()
                db.session.delete(group)
                db.session.commit()
            # 如果保留记录，不删除群组，只是没有成员了
            # 下次有人加入同名群聊时会加入这个群组
        else:
            # 如果离开的是群主，转移群主权限给最早加入的成员
            if group.owner_id == user.id:
                # 找到最早加入的成员
                oldest_member = GroupMember.query.filter_by(
                    group_id=group.id
                ).order_by(GroupMember.joined_at.asc()).first()

                if oldest_member:
                    group.owner_id = oldest_member.user_id
                    db.session.commit()

                    # 通知新群主
                    new_owner = db.session.get(User, oldest_member.user_id)
                    if new_owner:
                        new_owner_sid = usernames_to_sids.get(new_owner.username)
                        if new_owner_sid:
                            emit('became group owner', {
                                'group_name': group_name,
                                'message': f'您已成为群聊 "{group_name}" 的新群主'
                            }, room=new_owner_sid)

        emit('group left', {'group_name': group_name}, room=request.sid)


@socketio.on('check group members')
def handle_check_group_members(data):
    """检查群组成员数量"""
    user = get_current_user()
    group_name = data.get('group_name')

    if not user or not group_name:
        return

    group = Group.query.filter_by(name=group_name).first()
    if not group:
        emit('group member count', {'group_name': group_name, 'count': 0}, room=request.sid)
        return

    member_count = group.members.count()
    emit('group member count', {'group_name': group_name, 'count': member_count}, room=request.sid)


@socketio.on('get group members')
def handle_get_group_members(data):
    """获取群组成员列表"""
    user = get_current_user()
    group_name = data.get('group_name')

    if not user or not group_name:
        return

    group = Group.query.filter_by(name=group_name).first()
    if not group:
        emit('group members list', {'group_name': group_name, 'members': []}, room=request.sid)
        return

    # 获取所有成员信息
    members = []
    for membership in group.members:
        member_user = db.session.get(User, membership.user_id)
        if member_user:
            is_online = member_user.username in usernames_to_sids
            is_owner = member_user.id == group.owner_id
            members.append({
                'id': member_user.id,
                'username': member_user.username,
                'online': is_online,
                'is_owner': is_owner,
                'joined_at': membership.joined_at.strftime("%Y-%m-%d %H:%M:%S")
            })

    # 按照群主优先、在线优先、用户名排序
    members.sort(key=lambda x: (not x['is_owner'], not x['online'], x['username']))

    emit('group members list', {
        'group_name': group_name,
        'members': members,
        'owner_id': group.owner_id
    }, room=request.sid)


@socketio.on('kick group member')
def handle_kick_group_member(data):
    """群主踢出成员"""
    user = get_current_user()
    group_name = data.get('group_name')
    target_username = data.get('username')

    if not user or not group_name or not target_username:
        return

    group = Group.query.filter_by(name=group_name).first()
    if not group:
        emit('error', {'message': '群组不存在'}, room=request.sid)
        return

    # 检查是否是群主
    if group.owner_id != user.id:
        emit('error', {'message': '只有群主可以踢出成员'}, room=request.sid)
        return

    # 查找目标用户
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        emit('error', {'message': '用户不存在'}, room=request.sid)
        return

    # 不能踢出自己
    if target_user.id == user.id:
        emit('error', {'message': '不能踢出自己'}, room=request.sid)
        return

    # 查找成员关系
    member = GroupMember.query.filter_by(
        group_id=group.id, user_id=target_user.id
    ).first()

    if not member:
        emit('error', {'message': '该用户不是群成员'}, room=request.sid)
        return

    # 删除成员关系
    db.session.delete(member)
    db.session.commit()

    room_name = f"group-{group_name}"

    # 通知被踢出的用户
    target_sid = usernames_to_sids.get(target_username)
    if target_sid:
        emit('kicked from group', {
            'group_name': group_name,
            'kicked_by': user.username
        }, room=target_sid)
        # 让被踢用户离开房间
        leave_room(room_name, sid=target_sid)

    # 通知群内其他成员
    emit('member kicked', {
        'group_name': group_name,
        'username': target_username,
        'kicked_by': user.username
    }, room=room_name)

    # 更新成员列表给群主
    emit('kick success', {
        'group_name': group_name,
        'username': target_username
    }, room=request.sid)


@socketio.on('add private contact')
def handle_add_private_contact(data):
    """添加私聊联系人"""
    user = get_current_user()
    target_username = data.get('username')

    if not user or not target_username:
        return

    # 查找或创建目标用户
    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        target_user = User(username=target_username)
        db.session.add(target_user)
        db.session.commit()

    if target_user.id == user.id:
        return

    # 检查是否已存在
    existing = PrivateContact.query.filter_by(
        user_id=user.id, contact_id=target_user.id
    ).first()

    if not existing:
        contact = PrivateContact(user_id=user.id, contact_id=target_user.id)
        db.session.add(contact)
        db.session.commit()

    emit('private contact added', target_user.to_dict(), room=request.sid)


@socketio.on('remove private contact')
def handle_remove_private_contact(data):
    """删除私聊联系人"""
    user = get_current_user()
    target_username = data.get('username')

    if not user or not target_username:
        return

    target_user = User.query.filter_by(username=target_username).first()
    if not target_user:
        return

    contact = PrivateContact.query.filter_by(
        user_id=user.id, contact_id=target_user.id
    ).first()

    if contact:
        db.session.delete(contact)
        db.session.commit()

    emit('private contact removed', {'username': target_username}, room=request.sid)


# --- 消息撤回 ---
@socketio.on('recall message')
def handle_recall_message(data):
    """消息撤回"""
    user = get_current_user()
    message_id = data.get('id')

    if not user or not message_id:
        return

    recalled_text = f"{user.username} 撤回了一条消息"

    # 尝试在公共消息中查找
    message = Message.query.filter_by(id=message_id, sender_id=user.id).first()
    if message:
        message.text = recalled_text
        message.image = None
        message.thumbnail = None
        message.recalled = True
        message.reply_to_id = None
        db.session.commit()
        emit('message updated', message.to_dict(), broadcast=True)
        return

    # 尝试在群组消息中查找
    group_message = GroupMessage.query.filter_by(id=message_id, sender_id=user.id).first()
    if group_message:
        room = f"group-{group_message.group.name}"
        group_message.text = recalled_text
        group_message.image = None
        group_message.thumbnail = None
        group_message.recalled = True
        group_message.reply_to_id = None
        db.session.commit()
        emit('message updated', group_message.to_dict(), room=room)
        return

    # 尝试在私聊消息中查找
    private_message = PrivateMessage.query.filter_by(id=message_id, sender_id=user.id).first()
    if private_message:
        room = private_message.get_room_name()
        private_message.text = recalled_text
        private_message.image = None
        private_message.thumbnail = None
        private_message.recalled = True
        private_message.reply_to_id = None
        db.session.commit()
        emit('message updated', private_message.to_dict(), room=room)
        return


# --- 通知偏好设置 ---
@socketio.on('update preferences')
def handle_update_preferences(data):
    """更新用户通知偏好"""
    user = get_current_user()
    if not user:
        return

    if 'notification_sound' in data:
        user.notification_sound = bool(data['notification_sound'])
    if 'notification_browser' in data:
        user.notification_browser = bool(data['notification_browser'])
    if 'notification_title_flash' in data:
        user.notification_title_flash = bool(data['notification_title_flash'])

    db.session.commit()
    emit('preferences updated', user.to_dict(), room=request.sid)


# --- 正在输入状态 ---
@socketio.on('typing')
def handle_typing(data):
    """正在输入状态"""
    user = get_current_user()
    room = data.get('room')
    is_typing = data.get('typing', False)

    if not user or not room:
        return

    emit('user typing', {
        'username': user.username,
        'typing': is_typing,
        'room': room
    }, room=room, include_self=False)


# --- 主程序入口 ---
if __name__ == '__main__':
    # 创建数据库表
    with app.app_context():
        db.create_all()

    port = 3000
    try:
        port_input = input("请输入希望开放的端口号 (直接回车将使用默认端口 3000): ")
        if port_input:
            port = int(port_input)
    except ValueError:
        print(f"无效的端口号。将使用默认端口 {port}。")
    except Exception as e:
        print(f"发生错误: {e}。将使用默认端口 {port}。")

    print(f"服务器已启动，请访问 http://localhost:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
