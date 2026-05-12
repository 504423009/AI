import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-prod'
    UPLOAD_FOLDER = 'uploads'
    GENERATED_FOLDER = 'generated'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    # 你的 FAL API Key 将通过环境变量设置，这里不需要硬编码
