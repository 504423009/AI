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

# 确保目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ===================== 配置项 =====================
VPS_PUBLIC_BASE_URL = "http://187.127.116.116:5000"
API_KEY = "sk-317656c58f1e43d89ebe5a6d594ad274"
# ==================================================================

# 创建异步任务（修复了style参数）
def create_image_task(prompt, local_image_path, seed=None):
    if seed is None:
        seed = 42

    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable"
    }

    # 直接读取本地图片，转成base64传给阿里云
    try:
        with open(local_image_path, "rb") as f:
            img_bytes = f.read()
        base64_img = base64.b64encode(img_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{base64_img}"
    except Exception as e:
        print("❌ 读取本地图片失败:", e)
        return None

    data = {
        "model": "wanx-style-repaint-v1",
        "input": {
            "image_url": image_url,
            "prompt": prompt,
            "style_index": 1  # 用正确的参数，1=通用风格，变化明显
        },
        "parameters": {"seed": seed, "n": 1}
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        result = resp.json()
        print("阿里云完整返回:", result)
        task_id = result.get("output", {}).get("task_id")
        print("✅ 创建任务成功 task_id:", task_id)
        return task_id
    except Exception as e:
        print("❌ 请求阿里云失败:", e)
        return None

# 查询任务结果
def get_task_result(task_id):
    if not task_id:
        return None

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
                print(f"任务 {task_id} 生成失败")
                return None
        except Exception as e:
            print(f"轮询异常 重试中: {e}")
            continue
    print(f"任务 {task_id} 超时")
    return None

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

    if not uploaded_filename or not main_prompt:
        return jsonify({"error": "Missing parameters"}), 400

    source_image_path = os.path.join(app.config['UPLOAD_FOLDER'], uploaded_filename)

    # 固定生成 5 张，保证100%不缺图
    main_count = 1
    variant_count = 4

    suffix = "on clean white background, professional studio lighting, 8k high resolution, realistic product photography"
    final_main_prompt = f"{main_prompt}, {suffix}"

    task_list = []
    print("==== 开始批量创建任务 ====")
    
    for i in range(main_count):
        task_id = create_image_task(final_main_prompt, source_image_path)
        if task_id:
            task_list.append({"type": "main", "task_id": task_id})

    for i in range(variant_count):
        task_id = create_image_task(final_main_prompt, source_image_path)
        if task_id:
            task_list.append({"type": "variant", "task_id": task_id})

    generated_images = []
    print("==== 开始查询结果 ====")

    for item in task_list:
        img_url = get_task_result(item["task_id"])
        if not img_url:
            continue

        try:
            r = requests.get(img_url, timeout=20)
            if r.status_code == 200:
                saved_name = f"{item['type']}_{uuid.uuid4().hex}.png"
                save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                
                session['current_generated_files'].append(save_path)
                generated_images.append({"url": f"/generated_images/{saved_name}"})
        except:
            continue

    if not generated_images:
        return jsonify({"error": "Failed to generate any images"}), 500

    return jsonify({"images": generated_images})

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
