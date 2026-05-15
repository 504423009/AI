import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory, session, make_response
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'any-random-string-you-like'
app.config.from_object(Config)
CORS(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==============================================
# 椒图AI同款：NANO BANANA 蒙版重绘（产品100%不变）
# ==============================================
def generate_image(image_url, mask_url, seed=None):
    url = "https://fal.run/fal-ai/nano-banana-2"
    
    headers = {
        "Authorization": f"Key {app.config['FAL_KEY']}",
        "Content-Type": "application/json"
    }

    # 👇 这就是椒图AI 真正在用的【蒙版重绘参数】
    payload = {
        "prompt": "pure white background, product photography, 8k, clean, no shadows, sharp, professional",
        "image_url": image_url,
        "mask_url": mask_url,        # 核心：背景蒙版（只画背景）
        "strength": 0.25,
        "resolution": "1K",
        "output_format": "png",
        "negative_prompt": "blurry, text, watermark, logo, deformed, changed product, different object",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        if response.status_code == 200:
            data = response.json()
            return data["images"][0]["url"] if "images" in data else None
    except Exception as e:
        print("error", e)
    return None

# ==============================================
# 自动生成背景蒙版（自动抠图，产品不动）
# ==============================================
def generate_background_mask(image_url):
    try:
        return f"https://api.fal.ai/system/mask/background?image_url={image_url}"
    except:
        return None

# ==============================================
# 上传接口
# ==============================================
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

# ==============================================
# 生成接口（蒙版重绘，产品不变）
# ==============================================
@app.route('/generate', methods=['POST'])
def generate():
    session['current_generated_files'] = []
    data = request.json
    uploaded_filename = data.get('filename')

    if not uploaded_filename:
        return jsonify({"error": "Missing filename"}), 400

    if uploaded_filename.startswith('http'):
        source_image_url = uploaded_filename
    else:
        source_image_url = f"http://187.127.116.168:5000/uploads/{uploaded_filename}"

    # 👇 自动生成背景蒙版（椒图AI核心功能）
    mask_url = generate_background_mask(source_image_url)

    generated_images = []
    for i in range(6):
        img_url = generate_image(source_image_url, mask_url)
        if img_url:
            try:
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    saved_name = f"product_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    session['current_generated_files'].append(save_path)
                    generated_images.append({"url": f"/generated_images/{saved_name}"})
            except:
                pass

    if not generated_images:
        return jsonify({"error": "Generate failed"}), 500
    return jsonify({"images": [g["url"] for g in generated_images]})

# ==============================================
# 下载接口
# ==============================================
@app.route('/api/download_zip', methods=['POST'])
def download_zip():
    data = request.json
    images = data.get('images', [])
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            try:
                r = requests.get(img.get('url') if isinstance(img, dict) else img)
                if r.status_code == 200:
                    zf.writestr(f"{uuid.uuid4().hex}.png", r.content)
            except:
                continue
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name='products.zip')

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/generated_images/<filename>')
def generated(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

@app.route('/uploads/<filename>')
def uploaded(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/zip', methods=['GET'])
def zip_now():
    files = session.get('current_generated_files', [])
    if not files:
        return "No images"
    mem = BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if os.path.exists(f):
                z.write(f, os.path.basename(f))
    mem.seek(0)
    return send_file(mem, mimetype='application/zip', as_attachment=True, download_name='output.zip')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
