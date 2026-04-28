# image_utils.py - 图片处理工具模块
# 使用 Pillow 实现图片压缩和缩略图生成

from PIL import Image, ExifTags
import os
import uuid

# 配置常量
MAX_IMAGE_SIZE = (1920, 1080)  # 原图最大尺寸
THUMBNAIL_SIZE = (300, 300)    # 缩略图尺寸
JPEG_QUALITY = 85              # JPEG 压缩质量
THUMBNAIL_QUALITY = 70         # 缩略图压缩质量


def process_uploaded_image(file_storage, upload_folder):
    """
    处理上传的图片文件

    参数:
        file_storage: werkzeug.FileStorage 对象
        upload_folder: 上传文件夹路径

    返回:
        dict: {
            'original': 原图URL路径,
            'thumbnail': 缩略图URL路径,
            'success': bool,
            'error': 错误信息（如果有）
        }
    """
    try:
        # 读取图片
        image = Image.open(file_storage.stream)

        # 处理 EXIF 旋转信息
        image = fix_image_orientation(image)

        # 转换为 RGB（处理 PNG 透明通道等）
        if image.mode in ('RGBA', 'P'):
            # 创建白色背景
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            # 如果有 alpha 通道，使用它作为蒙版
            if image.mode == 'RGBA':
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # 生成唯一文件名
        unique_id = str(uuid.uuid4())
        original_filename = f"{unique_id}.jpg"
        thumbnail_filename = f"{unique_id}_thumb.jpg"

        # 确保目录存在
        os.makedirs(upload_folder, exist_ok=True)
        thumbnail_folder = os.path.join(upload_folder, 'thumbnails')
        os.makedirs(thumbnail_folder, exist_ok=True)

        # 处理原图（压缩和调整大小）
        original_image = resize_image(image.copy(), MAX_IMAGE_SIZE)
        original_path = os.path.join(upload_folder, original_filename)
        original_image.save(original_path, 'JPEG', quality=JPEG_QUALITY, optimize=True)

        # 生成缩略图
        thumbnail_image = create_thumbnail(image, THUMBNAIL_SIZE)
        thumbnail_path = os.path.join(thumbnail_folder, thumbnail_filename)
        thumbnail_image.save(thumbnail_path, 'JPEG', quality=THUMBNAIL_QUALITY, optimize=True)

        return {
            'success': True,
            'original': f"/uploads/{original_filename}",
            'thumbnail': f"/uploads/thumbnails/{thumbnail_filename}",
            'original_size': os.path.getsize(original_path),
            'thumbnail_size': os.path.getsize(thumbnail_path)
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def fix_image_orientation(image):
    """
    根据 EXIF 信息修正图片方向
    """
    try:
        # 获取 EXIF 数据
        exif = image._getexif()
        if exif is None:
            return image

        # 查找方向标签
        orientation_key = None
        for key, value in ExifTags.TAGS.items():
            if value == 'Orientation':
                orientation_key = key
                break

        if orientation_key is None or orientation_key not in exif:
            return image

        orientation = exif[orientation_key]

        # 根据方向值旋转图片
        if orientation == 2:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
        elif orientation == 3:
            image = image.rotate(180, expand=True)
        elif orientation == 4:
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
        elif orientation == 5:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            image = image.rotate(270, expand=True)
        elif orientation == 6:
            image = image.rotate(270, expand=True)
        elif orientation == 7:
            image = image.transpose(Image.FLIP_LEFT_RIGHT)
            image = image.rotate(90, expand=True)
        elif orientation == 8:
            image = image.rotate(90, expand=True)

    except (AttributeError, KeyError, IndexError):
        # 没有 EXIF 数据或处理失败，返回原图
        pass

    return image


def resize_image(image, max_size):
    """
    等比例缩放图片，使其不超过最大尺寸
    """
    if image.width <= max_size[0] and image.height <= max_size[1]:
        return image

    # 计算缩放比例
    ratio = min(max_size[0] / image.width, max_size[1] / image.height)
    new_size = (int(image.width * ratio), int(image.height * ratio))

    # 使用高质量重采样
    return image.resize(new_size, Image.Resampling.LANCZOS)


def create_thumbnail(image, size):
    """
    创建缩略图（居中裁剪为正方形，然后缩放）
    """
    # 复制图片避免修改原图
    img = image.copy()

    # 计算裁剪区域（居中正方形）
    width, height = img.size
    min_dim = min(width, height)

    left = (width - min_dim) // 2
    top = (height - min_dim) // 2
    right = left + min_dim
    bottom = top + min_dim

    # 裁剪为正方形
    img = img.crop((left, top, right, bottom))

    # 缩放到目标尺寸
    img = img.resize(size, Image.Resampling.LANCZOS)

    return img


def get_image_info(file_path):
    """
    获取图片信息
    """
    try:
        with Image.open(file_path) as img:
            return {
                'width': img.width,
                'height': img.height,
                'format': img.format,
                'mode': img.mode,
                'size_bytes': os.path.getsize(file_path)
            }
    except Exception as e:
        return {'error': str(e)}
