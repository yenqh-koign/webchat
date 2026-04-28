# models.py - 数据库模型定义
# 使用 SQLAlchemy ORM 实现数据持久化

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


def local_now():
    """返回本地时间"""
    return datetime.now()


class User(db.Model):
    """用户模型"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=local_now)
    last_seen = db.Column(db.DateTime, default=local_now)

    # 通知偏好设置
    notification_sound = db.Column(db.Boolean, default=True)
    notification_browser = db.Column(db.Boolean, default=True)
    notification_title_flash = db.Column(db.Boolean, default=True)

    # 注册登录相关字段
    user_type = db.Column(db.String(20), default='guest', nullable=False)  # 'guest' 或 'registered'
    password_hash = db.Column(db.String(255), nullable=True)  # bcrypt 密码哈希
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)  # 邮箱
    email_verified = db.Column(db.Boolean, default=False)  # 邮箱验证状态
    is_active = db.Column(db.Boolean, default=True)  # 账户激活状态
    registered_at = db.Column(db.DateTime, nullable=True)  # 注册时间

    # 关系
    sent_messages = db.relationship('Message', backref='sender', lazy='dynamic',
                                    foreign_keys='Message.sender_id')
    owned_groups = db.relationship('Group', backref='owner', lazy='dynamic')
    group_memberships = db.relationship('GroupMember', backref='user', lazy='dynamic',
                                        cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'notification_sound': self.notification_sound,
            'notification_browser': self.notification_browser,
            'notification_title_flash': self.notification_title_flash
        }


class Message(db.Model):
    """公共聊天消息模型"""
    __tablename__ = 'messages'

    id = db.Column(db.String(36), primary_key=True)  # UUID
    text = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)  # 原图路径
    thumbnail = db.Column(db.String(255), nullable=True)  # 缩略图路径
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reply_to_id = db.Column(db.String(36), db.ForeignKey('messages.id'), nullable=True)
    recalled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=local_now, index=True)

    # 自引用关系（回复）
    reply_to = db.relationship('Message', remote_side=[id], backref='replies')

    def to_dict(self, include_reply=True):
        data = {
            'id': self.id,
            'text': self.text,
            'image': self.image,
            'thumbnail': self.thumbnail,
            'username': self.sender.username if self.sender else None,
            'recalled': self.recalled,
            'timestamp': self.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        if include_reply and self.reply_to:
            data['replyTo'] = self.reply_to.to_dict(include_reply=False)
        else:
            data['replyTo'] = None
        return data


class Group(db.Model):
    """群组模型"""
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=local_now)

    # 关系
    members = db.relationship('GroupMember', backref='group', lazy='dynamic',
                              cascade='all, delete-orphan')
    messages = db.relationship('GroupMessage', backref='group', lazy='dynamic',
                               cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'owner': self.owner.username if self.owner else None,
            'member_count': self.members.count(),
            'created_at': self.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }


class GroupMember(db.Model):
    """群组成员关联表"""
    __tablename__ = 'group_members'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=local_now)

    # 复合唯一约束：同一用户不能重复加入同一群组
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='unique_group_member'),
    )


class GroupMessage(db.Model):
    """群组消息模型"""
    __tablename__ = 'group_messages'

    id = db.Column(db.String(36), primary_key=True)  # UUID
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    text = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    thumbnail = db.Column(db.String(255), nullable=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reply_to_id = db.Column(db.String(36), db.ForeignKey('group_messages.id'), nullable=True)
    recalled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=local_now, index=True)

    # 关系
    sender = db.relationship('User', backref='group_messages')
    reply_to = db.relationship('GroupMessage', remote_side=[id], backref='replies')

    def to_dict(self, include_reply=True):
        data = {
            'id': self.id,
            'text': self.text,
            'image': self.image,
            'thumbnail': self.thumbnail,
            'username': self.sender.username if self.sender else None,
            'recalled': self.recalled,
            'timestamp': self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            'room': f"group-{self.group.name}" if self.group else None
        }
        if include_reply and self.reply_to:
            data['replyTo'] = self.reply_to.to_dict(include_reply=False)
        else:
            data['replyTo'] = None
        return data


class PrivateMessage(db.Model):
    """私聊消息模型"""
    __tablename__ = 'private_messages'

    id = db.Column(db.String(36), primary_key=True)  # UUID
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(255), nullable=True)
    thumbnail = db.Column(db.String(255), nullable=True)
    reply_to_id = db.Column(db.String(36), db.ForeignKey('private_messages.id'), nullable=True)
    recalled = db.Column(db.Boolean, default=False)
    read = db.Column(db.Boolean, default=False)  # 已读状态
    created_at = db.Column(db.DateTime, default=local_now, index=True)

    # 关系
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_private_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_private_messages')
    reply_to = db.relationship('PrivateMessage', remote_side=[id], backref='replies')

    # 索引：加速私聊历史查询
    __table_args__ = (
        db.Index('idx_private_chat', 'sender_id', 'receiver_id', 'created_at'),
    )

    def to_dict(self, include_reply=True):
        data = {
            'id': self.id,
            'text': self.text,
            'image': self.image,
            'thumbnail': self.thumbnail,
            'username': self.sender.username if self.sender else None,
            'sender_id': self.sender_id,
            'receiver_id': self.receiver_id,
            'recalled': self.recalled,
            'read': self.read,
            'timestamp': self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            'room': self.get_room_name()
        }
        if include_reply and self.reply_to:
            data['replyTo'] = self.reply_to.to_dict(include_reply=False)
        else:
            data['replyTo'] = None
        return data

    def get_room_name(self):
        """生成私聊房间名（确保双方使用相同房间名）"""
        ids = sorted([self.sender_id, self.receiver_id])
        return f"private-{ids[0]}-{ids[1]}"

    @staticmethod
    def generate_room_name(user1_id, user2_id):
        """静态方法：根据两个用户ID生成房间名"""
        ids = sorted([user1_id, user2_id])
        return f"private-{ids[0]}-{ids[1]}"


class PrivateContact(db.Model):
    """私聊联系人列表"""
    __tablename__ = 'private_contacts'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contact_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=local_now)

    # 关系
    user = db.relationship('User', foreign_keys=[user_id], backref='contacts')
    contact = db.relationship('User', foreign_keys=[contact_id])

    # 复合唯一约束：同一用户不能重复添加同一联系人
    __table_args__ = (
        db.UniqueConstraint('user_id', 'contact_id', name='unique_private_contact'),
    )


class EmailVerification(db.Model):
    """邮箱验证码"""
    __tablename__ = 'email_verifications'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)  # 6位数字验证码
    purpose = db.Column(db.String(20), nullable=False)  # 'register' 或 'reset_password'
    created_at = db.Column(db.DateTime, default=local_now)
    expires_at = db.Column(db.DateTime, nullable=False)  # 10分钟后过期
    is_used = db.Column(db.Boolean, default=False)  # 是否已使用


class PasswordResetToken(db.Model):
    """密码重置令牌"""
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=local_now)
    expires_at = db.Column(db.DateTime, nullable=False)  # 1小时后过期
    is_used = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='reset_tokens')


class LoginSession(db.Model):
    """登录会话（记住我功能）"""
    __tablename__ = 'login_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    session_token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=local_now)
    expires_at = db.Column(db.DateTime, nullable=False)  # 7天后过期
    last_used_at = db.Column(db.DateTime, default=local_now)
    user_agent = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    user = db.relationship('User', backref='sessions')
