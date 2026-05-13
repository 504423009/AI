import os

class Config:
    # 密钥（如果没有设置环境变量，默认使用这一串）
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'

    # 用户上传的图片存放目录
    UPLOAD_FOLDER = 'uploads'

    # 生成的图片存放目录
    GENERATED_FOLDER = 'generated_images'

    # 最大内容长度 16MB
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # 👇 只新增了这一行，用来配置 Fal.ai API Key
    FAL_KEY = os.environ.get('FAL_KEY') or 'ff05126c-684b-4d8c-961f-9bf57bf0fec9:3c39fd05b24ae075c9d195d73dd38f61'
