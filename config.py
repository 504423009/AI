import os

class Config:
    # 密钥（如果没有设置环境变量，默认使用这一串）
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    
    # 用户上传的图片存放目录
    UPLOAD_FOLDER = 'uploads'
    
    # 【新增】生成的图片存放目录（你之前缺的就是这个）
    GENERATED_FOLDER = 'generated_images'
    
    # 最大内容长度 16MB
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    
    # 你的 FAL API Key 将通过环境变量设置，这里不需要硬编码
