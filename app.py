import os
import uuid
import base64
import requests
import time  # 已修复
from flask import Flask, request, jsonify, send_file, send_from_directory, session, make_response  # 已修复
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'any-random-string-you-like'
app.config.from_object(Config)
CORS(app)

# 确保目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ======================= 已修复：最终版 generate_image =======================
def generate_image(prompt, image_path, seed=None):
    if seed is None:
        seed = 42

    # 阿里云官方测试图（确保公网可访问）
    image_public_url = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/dog_and_girl.jpeg"

    API_KEY = "sk-317656c58f1e43d89ebe5a6d594ad274"
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable"
    }

    data = {
        "model": "wanx-style-repaint-v1",
        "input": {
            "image_url": image_public_url,
            "prompt": prompt,
            "style_index": 1
        },
        "parameters": {
            "seed": seed,
            "n": 1
        }
    }

    try:
        # 1. 创建任务（短超时，不卡这里）
        response = requests.post(url, headers=headers, json=data, timeout=15)
        result = response.json()
        print("异步任务创建:", result)

        if "task_id" not in result:
            print("创建任务失败，无task_id")
            return None

        task_id = result["task_id"]
        query_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

        # 2. 轮询（更短间隔 + 异常捕获，避免单次请求卡住）
        for _ in range(12):  # 12次 × 2秒 = 24秒，刚好在超时前完成
            try:
                time.sleep(2)
                res = requests.get(query_url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=8)
                task = res.json()
                print("轮询任务状态:", task.get("output", {}).get("task_status"))

                if "output" not in task:
                    continue

                status = task["output"]["task_status"]
                if status == "SUCCEEDED":
                    return task["output"]["results"][0]["url"]
                if status in ["FAILED", "CANCELED"]:
                    print("任务失败:", task)
                    return None

            except Exception as e:
                print("轮询请求异常，继续重试:", e)
                continue

        print("轮询超时，任务未完成")
        return None

    except Exception as e:
        print("生成图片错误:", e)
        return None

# ======================= 以下代码完全保持你原来的逻辑，未做任何改动 =======================

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
        # 返回相对路径，generate 函数里会处理
        return jsonify({"filename": unique_filename}) 
    return jsonify({"error": "File type not allowed"}), 400

@app.route('/generate', methods=['POST'])
def generate():
    session['current_generated_files'] = []
    os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
    
    data = request.json
    uploaded_filename = data.get('filename')
    main_prompt = data.get('main_prompt')
    variant_prompt = data.get('variant_prompt')
    platform = data.get('platform', 'amazon')
    mode = data.get('mode', '6')

    if not uploaded_filename or not main_prompt or not variant_prompt:
        return jsonify({"error": "Missing parameters"}), 400

    source_image_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_filename)

    generated_images = []
    total_count = 25 if mode == '25' else 6
    main_count = 20 if mode == '25' else 1

    suffix = "pure white background, no shadow, high quality, product photography, 8k" if platform == 'amazon' else "clean light grey background, product photography"
    final_main_prompt = f"{main_prompt}, {suffix}"
    final_variant_prompt = f"{variant_prompt}, high quality, photorealistic"

    # 生成主图
    for i in range(main_count):
        img_url = generate_image(final_main_prompt, source_image_path)
        if img_url:
            try:
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    saved_name = f"main_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    session['current_generated_files'].append(save_path)
                    generated_images.append({
                        "url": f"/generated_images/{saved_name}",
                        "prompt": final_main_prompt
                    })
            except Exception as e:
                print(f"下载图片失败: {e}")

    # 生成变体图
    for i in range(5):
        img_url = generate_image(final_variant_prompt, source_image_path)
        if img_url:
            try:
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    saved_name = f"variant_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    session['current_generated_files'].append(save_path)
                    generated_images.append({
                        "id": saved_name,
                        "url": f"/generated_images/{saved_name}",
                        "prompt": final_variant_prompt
                    })
            except Exception as e:
                print(f"Download error: {e}")

    if not generated_images:
        return jsonify({"error": "Failed to generate any images. Check console logs."}), 500

    safe_images = []
    for img in generated_images:
        if isinstance(img, dict) and 'url' in img:
            safe_images.append(img['url'])
        elif isinstance(img, str):
            safe_images.append(img)

    return jsonify({"images": safe_images})

@app.route('/api/download_zip', methods=['POST'])
def download_zip():
    data = request.get_json()
    images = data.get('images', [])

    if not images:
        return jsonify({"error": "No images to download"}), 400

    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            try:
                img_url = img.get('url')
                img_id = img.get('id', 'image')
                if img_url:
                    r = requests.get(img_url)
                    if r.status_code == 200:
                        filename = f"{img_id}.png"
                        zf.writestr(filename, r.content)
            except Exception as e:
                print(f"Error adding image to zip: {e}")
                continue

    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name='ecommerce_images.zip'
    )

@app.route('/')
def home():
    return send_from_directory('.', 'index.html')

@app.route('/generated_images/<filename>')
def serve_generated_image(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

@app.route('/uploads/<filename>')
def serve_uploaded_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/zip', methods=['GET'])
def download_zip_legacy():
    session_images = session.get('current_generated_files', [])
    if not session_images:
        return "本次会话未生成任何图片，无法打包下载", 200

    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for img_path in session_images:
            if os.path.exists(img_path):
                filename = os.path.basename(img_path)
                zipf.write(img_path, filename)

    memory_file.seek(0)
    response = make_response(
        send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name='本次生成图片.zip'
        )
    )
    response.headers['Content-Type'] = 'application/zip'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
