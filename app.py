import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory, session, make_response
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO
from PIL import Image

app = Flask(__name__)
app.secret_key = 'any-random-string-you-like'
app.config.from_object(Config)
CORS(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ------------------------------------------
# 步骤1：调用免费抠图API 得到透明背景产品
# ------------------------------------------
def remove_bg_api(image_path):
    try:
        url = "https://api.remove.bg/v1.0/removebg"
        files = {
            'image_file': open(image_path, 'rb'),
        }
        data = {
            'size': '1024x1024'
        }
        headers = {
            'X-Api-Key': 'Y85a11111111111111111111'  # 免费key
        }
        response = requests.post(url, files=files, data=data, headers=headers)
        if response.status_code == 200:
            out_path = image_path.rsplit('.',1)[0] + "_transparent.png"
            with open(out_path, 'wb') as f:
                f.write(response.content)
            return out_path
    except:
        pass
    return None

# ------------------------------------------
# 步骤2：AI生成电商背景（NanoBanana）
# ------------------------------------------
def generate_background_image():
    url = "https://fal.run/fal-ai/nano-banana-2"
    headers = {
        "Authorization": f"Key {app.config['FAL_KEY']}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": "pure white background, clean studio, soft light, product photography background",
        "resolution": "1K",
        "output_format": "png"
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code == 200:
            data = response.json()
            img_url = data["images"][0]["url"]
            img_data = requests.get(img_url).content
            bg_path = os.path.join(app.config['GENERATED_FOLDER'], f"bg_{uuid.uuid4().hex}.png")
            with open(bg_path, 'wb') as f:
                f.write(img_data)
            return bg_path
    except:
        pass
    return None

# ------------------------------------------
# 步骤3：合成（产品贴在AI背景上 → 产品不变！）
# ------------------------------------------
def composite_product(product_path, bg_path):
    product = Image.open(product_path).convert("RGBA")
    bg = Image.open(bg_path).convert("RGBA")
    
    # 产品缩放到合适大小
    max_size = 900
    w, h = product.size
    if w > h:
        new_w = max_size
        new_h = int(max_size * h / w)
    else:
        new_h = max_size
        new_w = int(max_size * w / h)
    product = product.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 居中
    bg_w, bg_h = bg.size
    offset = ((bg_w - new_w) // 2, (bg_h - new_h) // 2)
    bg.paste(product, offset, mask=product)

    out_path = os.path.join(app.config['GENERATED_FOLDER'], f"final_{uuid.uuid4().hex}.png")
    bg.save(out_path)
    return out_path

# ------------------------------------------
# 核心生成接口
# ------------------------------------------
@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({"error": "Missing filename"}), 400

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    # 1. 抠图
    product_transparent = remove_bg_api(file_path)
    if not product_transparent:
        return jsonify({"error": "抠图失败"}), 500

    final_images = []
    for i in range(6):
        # 2. 生成AI背景
        bg_img = generate_background_image()
        if not bg_img:
            continue
        
        # 3. 合成（产品不变！）
        final_img = composite_product(product_transparent, bg_img)
        final_images.append(f"/generated_images/{os.path.basename(final_img)}")

    return jsonify({"images": final_images})

# ------------------------------------------
# 上传接口
# ------------------------------------------
@app.route('/upload', methods=['POST'])
@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        return jsonify({"filename": unique_filename})
    return jsonify({"error": "File type not allowed"}), 400

# ------------------------------------------
# 静态文件访问
# ------------------------------------------
@app.route('/generated_images/<filename>')
def serve_generated(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

@app.route('/uploads/<filename>')
def serve_uploaded(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
