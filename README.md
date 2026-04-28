# WebChat

一个基于 Flask 和 Socket.IO 的网页即时通讯应用，支持访客进入、注册登录、公共聊天、私聊、群聊、图片发送和基础消息管理。数据默认保存在本地 SQLite 数据库中，适合局域网或小范围自托管使用。

## 功能特性

- 访客模式、账号注册、登录和记住登录状态
- 可选邮箱验证码注册与密码重置
- 公共聊天室、私聊、群聊
- 在线用户列表和未读消息提示
- 文本消息、图片上传、缩略图生成
- 消息回复和撤回
- 深色/浅色主题切换
- SQLite 本地数据存储

## 技术栈

- Python
- Flask
- Flask-SocketIO
- Flask-SQLAlchemy
- SQLite
- Pillow
- bcrypt

## 目录结构

```text
WebChat/
├── app.py              # 应用入口和 Socket.IO 事件
├── auth_routes.py      # 注册、登录、密码重置接口
├── auth_utils.py       # 密码哈希、验证码、令牌工具
├── config.py           # 应用配置
├── email_utils.py      # 邮件发送工具
├── image_utils.py      # 图片压缩和缩略图处理
├── models.py           # SQLAlchemy 数据模型
├── static/             # 前端静态资源
├── templates/          # 页面模板
├── .env.example        # 环境变量示例
└── app.spec            # PyInstaller 打包配置
```

## 本地运行

创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

安装依赖：

```powershell
pip install -r requirements.txt
```

准备环境变量：

```powershell
Copy-Item .env.example .env
```

按需编辑 `.env` 中的 `SECRET_KEY`、`MAIL_USERNAME`、`MAIL_PASSWORD` 等配置。

启动应用：

```powershell
python app.py
```

默认访问地址：

```text
http://127.0.0.1:5000
```

## 环境变量

```env
SECRET_KEY=your-random-secret-key-here-change-in-production
MAIL_USERNAME=your_qq_email@qq.com
MAIL_PASSWORD=your_qq_smtp_authorization_code_16_chars
EMAIL_VERIFICATION_ENABLED=true
```

如果不需要邮箱验证码，可以将 `EMAIL_VERIFICATION_ENABLED` 设置为 `false`。

## 打包

项目保留了 PyInstaller 配置文件，可按需安装 PyInstaller 后构建可执行文件：

```powershell
pip install pyinstaller
pyinstaller app.spec
```

构建产物会生成在 `dist/` 和 `build/` 中。
