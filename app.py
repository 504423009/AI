import os
import uuid
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from config import Config
from werkzeug.utils import secure_filename
import zipfile
from io import BytesIO

app = Flask(__name__)
app.secret_key = 'any-random-string-you-like'  # 随便写个字符串，比如 'my-secret-123'
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
    # 最稳电商模型：SDXL 1.0
    url = "https://fal.run/fal-ai/stable-diffusion-xl-v1-base"

    headers = {
        "Authorization": f"Key {app.config['FAL_KEY']}",
        "Content-Type": "application/json"
    }

    # 强制保护：产品100%不变，只改背景
    protect_prompt = "产品主体完全保持不变，颜色、款式、形状、细节100%保留，不修改、不变形、不扭曲，仅更换背景、优化光影，"
    final_prompt = protect_prompt + prompt

    # 核心：ControlNet 锁死产品
    payload = {
        "prompt": final_prompt,
        "image_url": image_url,
        "image_strength": 0.1,
        "steps": 28,
        "cfg_scale": 7.5,
        "enable_safety_checker": True,
        "output_format": "png",
        "controlnets": [
            {
                "type": "canny",
                "image_url": image_url,
                "strength": 1.0
            }
        ]
    }

    if seed:
        payload["seed"] = seed

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
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
    except Exception as e:
        print(f"Request Exception: {e}")
        return None

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
        return jsonify({"filename": unique_filename}) # 只返回文件名即可
    return jsonify({"error": "File type not allowed"}), 400

@app.route('/generate', methods=['POST'])
def generate():
    from flask import session
    session['current_generated_files'] = []
    os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
    # 👇 就在这里插入这两行打印代码
    print("🔍 收到原始请求数据:", request.get_data(as_text=True))
    print("🔍 解析后的 JSON:", request.json)
    
    data = request.json
    uploaded_filename = data.get('filename')
    main_prompt = data.get('main_prompt')
    variant_prompt = data.get('variant_prompt')
    platform = data.get('platform', 'amazon') # 默认值设为 'amazon'
    mode = data.get('mode', '6') # 默认值设为 '6'

    if not uploaded_filename or not main_prompt or not variant_prompt:
        return jsonify({"error": "Missing parameters"}), 400

    # 1. 准备原图 URL
    # 注意：Fal.ai 需要公网可访问的 URL。
    # 如果是在本地或没有域名的 VPS 上运行，这里会失败。
    # 解决方案：你需要先将图片上传到图床，或者使用 Fal 的文件上传 API。
    # 为了演示，这里假设 uploaded_filename 是一个公网 URL，或者你需要实现 Fal 文件上传。
    # 临时方案：如果 uploaded_filename 不是 http 开头，我们尝试读取本地文件并上传到 Fal (模拟)
    # 实际项目中，建议在前端上传完图后，直接把图的公网链接传给后端，或者后端先上传图。
    # 这里假设 uploaded_filename 是本地文件名，我们需要构建一个能访问的路径
    # 但 Fal 无法访问你本地的 127.0.0.1。
    # **重要提示**：这段代码在本地 VPS 运行时，如果不做内网穿透，Fal API 会报错找不到图片。
    # 这里的逻辑是：如果用户传的是文件名，我们尝试构造一个本地路径（仅用于演示逻辑，实际会失败除非有公网IP）
    # 为了演示成功，建议你在前端直接传入一个网络图片地址，或者实现 Fal 的文件上传。
    if not uploaded_filename.startswith('http'):
        source_image_url = f"http://187.127.116.168:5000/uploads/{uploaded_filename}"
    else:
        source_image_url = uploaded_filename

    generated_images = []
    total_count = 25 if mode == '25' else 6
    main_count = 20 if mode == '25' else 1

    # 提示词后缀
    suffix = "pure white background, no shadow, high quality, product photography, 8k" if platform == 'amazon' else "clean light grey background, product photography"
    final_main_prompt = f"{main_prompt}, {suffix}"
    final_variant_prompt = f"{variant_prompt}, high quality, photorealistic"

    # 生成主图
    for i in range(main_count):
        img_url = generate_image(final_main_prompt, source_image_url)
        if img_url:
            # 下载图片保存到本地
            try:
                print(f"开始下载图片: {img_url}")
                r = requests.get(img_url, timeout=30)
                print(f"下载状态码: {r.status_code}")
                if r.status_code == 200:
                    saved_name = f"main_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    print(f"保存路径: {save_path}")
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    print(f"图片保存成功: {save_path}")
                    session['current_generated_files'].append(save_path)
                    generated_images.append({
                        "url": f"/generated_images/{saved_name}",
                        "prompt": final_main_prompt
                    })
            except Exception as e:
                print(f"下载图片失败: {e}")
                import traceback
                traceback.print_exc()

    # 生成变体图
    for i in range(5):
        img_url = generate_image(final_variant_prompt, source_image_url)
        if img_url:
            try:
                r = requests.get(img_url, timeout=30) # ✅ 加超时，防止卡住
                if r.status_code == 200:
                    saved_name = f"variant_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    print(f"图片保存成功: {save_path}")
                    session['current_generated_files'].append(save_path)
                    
                    generated_images.append({
                        "id": saved_name,
                        "url": f"/generated_images/{saved_name}", # ✅ 核心：统一返回本地路径
                        "prompt": final_variant_prompt
                    })
            except Exception as e:
                print(f"Download error: {e}")
                import traceback
                traceback.print_exc() # ✅ 打印完整错误堆栈，方便排查

    if not generated_images:
        return jsonify({"error": "Failed to generate any images. Check API Key or Source Image URL."}), 500

    # 数据清洗：只提取有效的图片链接
    safe_images = []
    for img in generated_images:
        if isinstance(img, dict) and 'url' in img:
            safe_images.append(img['url'])
        elif isinstance(img, str):
            safe_images.append(img)

    print("### 最终返回给前端的链接：", safe_images) # 在终端打印看看
    return jsonify({"images": safe_images})

@app.route('/api/download_zip', methods=['POST']) # 修改为 POST
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
                        # 简单的文件名清理
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

# 生成图片的静态访问路由
@app.route('/generated_images/<filename>')
def serve_generated_image(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

# 上传图片的静态访问路由（让fal.ai能读到用户上传的原图）
@app.route('/uploads/<filename>')
def serve_uploaded_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# 下载ZIP接口（独立实现，绕过JSON校验，只打包当前会话图片）
@app.route('/zip', methods=['GET'])
def download_zip_legacy():
    import os
    import zipfile
    from io import BytesIO
    from flask import make_response, send_file, session

    # 核心：只读取当前会话生成的图片列表
    session_images = session.get('current_generated_files', [])
    if not session_images:
        return "本次会话未生成任何图片，无法打包下载", 200

    # 只打包本次生成的图片，不会包含历史文件
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for img_path in session_images:
            if os.path.exists(img_path):
                filename = os.path.basename(img_path)
                zipf.write(img_path, filename)

    memory_file.seek(0)

    # 强制设置响应头，绕过JSON校验
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
