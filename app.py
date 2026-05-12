import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory,render_template
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# 确保目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_image(prompt, image_url, seed=None):
    """调用 Fal.ai API 生成图片"""
    url = "https://fal.run/fal-ai/flux/dev"  # 使用 Flux Dev 模型，也可以换成schnell速度更快
    headers = {
        "Authorization": f"Key {app.config['FAL_KEY']}",
        "Content-Type": "application/json"
    }
    
    # 根据是否提供Seed来构造请求体
    payload = {
        "prompt": prompt,
        "image_url": image_url,
        "enable_safety_checker": True,
        "output_format": "png" 
    }
    
    if seed:
        payload["seed"] = seed
        
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 201:
        data = response.json()
        # 获取图片URL (Flux模型返回结构可能不同，需调试)
        # 这里假设返回结构包含 image 或 images 字段
        if 'images' in data and len(data['images']) > 0:
             return data['images'][0]['url']
        elif 'image' in data:
             return data['image']['url']
        else:
            print(f"Error parsing response: {data}")
            return None
    else:
        print(f"API Error: {response.status_code}, {response.text}")
        return None

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # 使用uuid避免文件名冲突
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        return jsonify({"filename": unique_filename, "path": file_path})
    return jsonify({"error": "File type not allowed"}), 400

@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.json
    uploaded_filename = data.get('filename')
    main_prompt = data.get('main_prompt')
    variant_prompt = data.get('variant_prompt')
    platform = data.get('platform') # amazon or shein
    mode = data.get('mode') # 6 or 25

    if not uploaded_filename or not main_prompt or not variant_prompt:
        return jsonify({"error": "Missing parameters"}), 400

    # 构造源图片的访问URL (Fal.ai 需要公网可访问的URL)
    # 注意：在生产环境中，这里应该上传到 S3 或者使用 ngrok 映射本地地址
    # 为了演示，假设 VPS 有公网IP且 Flask 正在运行，这里需要处理内网穿透或临时上传逻辑
    # 简单起见，我们假设用户上传图片后，我们将其临时托管或用户直接提供URL
    # 在此脚本逻辑中，我们将模拟一个流程：
    
    # 实际逻辑：
    # 1. 用户上传图 -> 保存到本地
    # 2. 为了传给 Fal，我们需要一个公网 URL。
    #    方案A: 使用 Fal 的临时上传 API (推荐)
    #    方案B: 使用 VPS 公网 IP (需要配置 Nginx)
    
    # 这里为了代码完整性，我们假设通过 Fal 上传了图片并获得了 image_url
    # 真实场景需实现 Fal 的文件上传接口
    
    generated_images = []
    
    # 模拟生成过程
    total_count = 25 if mode == '25' else 6
    main_count = 20 if mode == '25' else 1
    
    # 1. 生成首图
    # 这里需要根据平台规则拼接 Prompt
    # Amazon: 纯白底，无阴影
    suffix = "pure white background, no shadow, high quality, product photography, 8k" if platform == 'amazon' else "clean light grey background, product photography"
    
    final_main_prompt = f"{main_prompt}, {suffix}"
    
    # 这里调用 API (伪代码，因为缺少 Fal 图片上传步骤)
    # image_url = upload_to_fal(os.path.join(app.config['UPLOAD_FOLDER'], uploaded_filename))
    
    for i in range(main_count):
        # 实际调用函数
        # img_url = generate_image(final_main_prompt, image_url)
        # 模拟返回
        generated_images.append({
            "id": f"main_{i+1}",
            "url": "/static/placeholder.jpg", # 占位符
            "prompt": final_main_prompt
        })
        
    # 2. 生成变体图
    # 变体图通常不需要纯白底，而是场景
    final_variant_prompt = f"{variant_prompt}, high quality, photorealistic"
    
    for i in range(5):
        # img_url = generate_image(final_variant_prompt, image_url)
        generated_images.append({
            "id": f"variant_{i+1}",
            "url": "/static/placeholder.jpg",
            "prompt": final_variant_prompt
        })

    return jsonify({"images": generated_images})

@app.route('/api/download-zip', methods=['POST'])
def download_zip():
    data = request.json
    images = data.get('images', [])
    
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            # 下载图片内容并写入zip
            # 实际需从 URL 获取内容
            # r = requests.get(img['url'])
            # zf.writestr(f"{img['id']}.jpg", r.content)
            pass # 模拟
            
    memory_file.seek(0)
return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name='ecommerce_images.zip')

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
