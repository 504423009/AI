import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO
from PIL import Image
import traceback

app = Flask(__name__)
app.secret_key = 'any-random-string-you-like'
app.config.from_object(Config)
CORS(app)

# 配置目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --------------------------
# 步骤1：调用 remove.bg 抠图（透明背景产品）
# --------------------------
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
            # 👉 这里替换成你自己的 remove.bg API Key！
            'X-Api-Key': '9mbvyw8YqCpRM1JZVNYHupq4'
        }
        response = requests.post(url, files=files, data=data, headers=headers, timeout=30)
        if response.status_code == 200:
            out_path = os.path.join(
                app.config['UPLOAD_FOLDER'],
                f"{uuid.uuid4().hex}_transparent.png"
            )
            with open(out_path, 'wb') as f:
                f.write(response.content)
            print(f"✅ 抠图成功：{out_path}")
            return out_path
        else:
            print(f"❌ 抠图失败，状态码：{response.status_code}，响应：{response.text}")
            return None
    except Exception as e:
        print(f"❌ 抠图异常：{e}")
        traceback.print_exc()
        return None

# --------------------------
# 步骤2：用 NanoBanana 生成电商背景
# --------------------------
def generate_background_image():
    try:
        url = "https://fal.run/fal-ai/nano-banana-2"
        headers = {
            "Authorization": f"Key {app.config['FAL_KEY']}",
            "Content-Type": "application/json"
        }
        payload = {
            "prompt": "pure white background, clean studio product photography background, soft light, no shadows, high quality",
            "resolution": "1K",
            "output_format": "png"
        }
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        if response.status_code == 200:
            data = response.json()
            img_url = data["images"][0]["url"]
            img_data = requests.get(img_url, timeout=30).content
            bg_path = os.path.join(
                app.config['GENERATED_FOLDER'],
                f"bg_{uuid.uuid4().hex}.png"
            )
            with open(bg_path, 'wb') as f:
                f.write(img_data)
            print(f"✅ 背景生成成功：{bg_path}")
            return bg_path
        else:
            print(f"❌ 背景生成失败，状态码：{response.status_code}，响应：{response.text}")
            return None
    except Exception as e:
        print(f"❌ 背景生成异常：{e}")
        traceback.print_exc()
        return None

# --------------------------
# 步骤3：产品贴到AI背景上（产品100%不变）
# --------------------------
def composite_product(product_path, bg_path):
    try:
        product = Image.open(product_path).convert("RGBA")
        bg = Image.open(bg_path).convert("RGBA")
        
        # 产品缩放到背景的90%大小，居中放置
        max_size = 900
        w, h = product.size
        if w > h:
            new_w = max_size
            new_h = int(max_size * h / w)
        else:
            new_h = max_size
            new_w = int(max_size * w / h)
        product = product.resize((new_w, new_h), Image.Resampling.LANCZOS)

        bg_w, bg_h = bg.size
        offset = ((bg_w - new_w) // 2, (bg_h - new_h) // 2)
        bg.paste(product, offset, mask=product)

        out_path = os.path.join(
            app.config['GENERATED_FOLDER'],
            f"final_{uuid.uuid4().hex}.png"
        )
        bg.save(out_path)
        print(f"✅ 合成成功：{out_path}")
        return out_path
    except Exception as e:
        print(f"❌ 合成异常：{e}")
        traceback.print_exc()
        return None

# --------------------------
# 上传接口
# --------------------------
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
        print(f"✅ 上传成功：{file_path}")
        return jsonify({"filename": unique_filename})
    return jsonify({"error": "File type not allowed"}), 400

# --------------------------
# 生成接口（核心流程）
# --------------------------
@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        filename = data.get('filename')
        if not filename:
            return jsonify({"error": "Missing filename"}), 400

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404

        print(f"📌 开始处理文件：{file_path}")

        # 1. 抠图
        product_transparent = remove_bg_api(file_path)
        if not product_transparent:
            return jsonify({"error": "抠图失败，请检查remove.bg API Key"}), 500

        final_images = []
        for i in range(6):
            # 2. 生成AI背景
            bg_img = generate_background_image()
            if not bg_img:
                continue
            
            # 3. 合成（产品不变！）
            final_img = composite_product(product_transparent, bg_img)
            if final_img:
                final_images.append(f"/generated_images/{os.path.basename(final_img)}")

        if not final_images:
            return jsonify({"error": "所有图片生成失败，请检查FAL API Key"}), 500

        print(f"✅ 生成完成，共 {len(final_images)} 张图片")
        return jsonify({"images": final_images})

    except Exception as e:
        print(f"❌ 生成接口异常：{e}")
        traceback.print_exc()
        return jsonify({"error": "服务器内部错误，请查看控制台日志"}), 500

# --------------------------
# 静态文件访问接口
# --------------------------
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
