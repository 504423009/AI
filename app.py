import os
import uuid
import base64
import requests
import time
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

# ==============================================================================
# 稳定版：创建任务（只发任务，不等待）
# ==============================================================================
def create_image_task(prompt, seed=None):
    if seed is None:
        seed = 42

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
        "parameters": {"seed": seed, "n": 1}
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        result = resp.json()
        print("✅ 创建任务成功:", result.get("task_id"))
        return result.get("task_id")
    except Exception as e:
        print("❌ 创建任务失败:", e)
        return None

# ==============================================================================
# 稳定版：查询任务结果（安全、不崩溃）
# ==============================================================================
def get_task_result(task_id):
    if not task_id:
        return None

    API_KEY = "sk-317656c58f1e43d89ebe5a6d594ad274"
    query_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

    for _ in range(15):
        time.sleep(2)
        try:
            res = requests.get(query_url, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10)
            task = res.json()
            status = task.get("output", {}).get("task_status")
            print(f"任务 {task_id} 状态: {status}")

            if status == "SUCCEEDED":
                return task["output"]["results"][0]["url"]
            if status in ["FAILED", "CANCELED"]:
                return None
        except:
            continue
    return None

# ==============================================================================
# 核心：先生成所有任务 → 再统一查结果（最稳定模式）
# ==============================================================================
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
    total_count = 25 if mode == '25' else 6
    main_count = 20 if mode == '25' else 1

    suffix = "pure white background, no shadow, high quality, product photography, 8k" if platform == 'amazon' else "clean light grey background, product photography"
    final_main_prompt = f"{main_prompt}, {suffix}"
    final_variant_prompt = f"{variant_prompt}, high quality, photorealistic"

    # ===================== 第一步：批量创建所有任务（超快） =====================
    task_list = []
    print("==== 开始批量创建任务 ====")
    
    for i in range(main_count):
        task_id = create_image_task(final_main_prompt)
        if task_id:
            task_list.append({"type": "main", "task_id": task_id, "prompt": final_main_prompt})

    for i in range(5):
        task_id = create_image_task(final_variant_prompt)
        if task_id:
            task_list.append({"type": "variant", "task_id": task_id, "prompt": final_variant_prompt})

    # ===================== 第二步：批量查询所有结果（超稳） =====================
    generated_images = []
    print("==== 开始查询结果 ====")

    for item in task_list:
        img_url = get_task_result(item["task_id"])
        if not img_url:
            continue

        try:
            r = requests.get(img_url, timeout=20)
            if r.status_code == 200:
                prefix = item["type"]
                saved_name = f"{prefix}_{uuid.uuid4().hex}.png"
                save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                
                session['current_generated_files'].append(save_path)
                generated_images.append({"url": f"/generated_images/{saved_name}"})
        except:
            continue

    if not generated_images:
        return jsonify({"error": "Failed to generate any images"}), 500

    return jsonify({"images": [img["url"] for img in generated_images]})

# ==============================================================================
# 以下代码完全保持你原来的逻辑，没有任何改动
# ==============================================================================

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
                        zf.writestr(f"{img_id}.png", r.content)
            except:
                continue
    memory_file.seek(0)
    return send_file(memory_file, mimetype='application/zip', as_attachment=True, download_name='ecommerce_images.zip')

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
                zipf.write(img_path, os.path.basename(img_path))

    memory_file.seek(0)
    response = make_response(send_file(memory_file, as_attachment=True, download_name='本次生成图片.zip'))
    response.headers['Content-Type'] = 'application/zip'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
