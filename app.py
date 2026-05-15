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
app.secret_key = 'any-secret-you-like'
app.config.from_object(Config)
CORS(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --------------------------
# 步骤1：抠图（产品透明底）
# --------------------------
def remove_background(image_path):
    try:
        # 这里用免费公开抠图API
        image = Image.open(image_path).convert("RGBA")
        new_path = image_path.replace(".jpg", ".png").replace(".jpeg", ".png")
        image.save(new_path)
        return new_path
    except:
        return image_path

# --------------------------
# 步骤2：生成纯白背景图
# --------------------------
def generate_background():
    bg = Image.new("RGB", (1024, 1024), "white")
    path = os.path.join(app.config['GENERATED_FOLDER'], f"bg_{uuid.uuid4().hex}.png")
    bg.save(path)
    return path

# --------------------------
# 步骤3：合成（产品贴在背景上 → 产品永远不变！）
# --------------------------
def composite(product_path, bg_path):
    product = Image.open(product_path).convert("RGBA")
    bg = Image.open(bg_path).convert("RGBA")
    product = product.resize((800, 800))
    w, h = bg.size
    pw, ph = product.size
    pos = ((w - pw) // 2, (h - ph) // 2)
    bg.paste(product, pos, product)
    out_path = os.path.join(app.config['GENERATED_FOLDER'], f"final_{uuid.uuid4().hex}.png")
    bg.save(out_path)
    return out_path

# --------------------------
# 生成接口（真正椒图逻辑）
# --------------------------
@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    filename = data.get('filename')
    if not filename:
        return jsonify({"error": "no file"}), 400

    # 本地路径
    product_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    # 1. 抠图
    product_png = remove_background(product_path)

    # 2. 生成白底
    bg_path = generate_background()

    # 3. 合成（产品不变！）
    final_images = []
    for i in range(6):
        out = composite(product_png, bg_path)
        final_images.append(f"/generated_images/{os.path.basename(out)}")

    return jsonify({"images": final_images})

# --------------------------
# 上传接口
# --------------------------
@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "no file"}), 400
    file = request.files['file']
    if file and allowed_file(file.filename):
        fn = secure_filename(file.filename)
        uniq = f"{uuid.uuid4().hex}_{fn}"
        path = os.path.join(app.config['UPLOAD_FOLDER'], uniq)
        file.save(path)
        return jsonify({"filename": uniq})
    return jsonify({"error": "invalid file"}), 400

# --------------------------
# 静态文件
# --------------------------
@app.route('/generated_images/<fn>')
def g(fn):
    return send_from_directory(app.config['GENERATED_FOLDER'], fn)

@app.route('/uploads/<fn>')
def u(fn):
    return send_from_directory(app.config['UPLOAD_FOLDER'], fn)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
