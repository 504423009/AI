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
app.secret_key = 'any-random-string-you-like'
app.config.from_object(Config)
CORS(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ------------------- 关键修复：适配 Nano Banana 2 以图生图 -------------------
def clean_prompt(prompt):
    """清理提示词，去掉中文指令，只保留模型能理解的英文描述"""
    # 移除所有中文指令，只保留后面的英文部分
    if "帮我生成" in prompt or "分析产品" in prompt:
        # 提取逗号后面的描述部分
        parts = prompt.split(',')
        cleaned = [p for p in parts if not any(c in p for c in ["帮我生成", "分析产品"])]
        return ','.join(cleaned).strip()
    return prompt

def generate_image(prompt, image_url, seed=None):
    """调用 Fal.ai Nano Banana 2 API 以图生图（修复版）"""
    url = "https://fal.run/fal-ai/nano-banana-2"
    headers = {
        "Authorization": f"Key {app.config['FAL_KEY']}",
        "Content-Type": "application/json"
    }

    # 1. 先清理提示词，去掉中文指令
    cleaned_prompt = clean_prompt(prompt)
    print(f"清理后的提示词: {cleaned_prompt}")

    # 2. 严格按照 Nano Banana 2 官方文档配置以图生图参数
    payload = {
        "prompt": cleaned_prompt,
        "image_url": image_url,
        "image_strength": 0.12,  # 产品图专用值，极低强度，保证原图产品不被改
        "resolution": "1K",
        "output_format": "png",
        "num_images": 1,
        "safety_tolerance": 4,
        "negative_prompt": "blurry, low quality, ugly, deformed, watermark, text, bad anatomy, disfigured, extra limbs, cropped"
    }

    if seed:
        payload["seed"] = seed

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        print(f"API响应状态码: {response.status_code}")
        print(f"API响应内容: {response.text[:500]}...")  # 打印部分响应，方便排查
        
        if response.status_code == 200:
            data = response.json()
            if 'images' in data and len(data['images']) > 0:
                return data['images'][0]['url']
            else:
                print(f"API返回无图片: {data}")
                return None
        else:
            print(f"API错误 {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"请求异常: {e}")
        return None
# -------------------------------------------------------------------

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

@app.route('/generate', methods=['POST'])
def generate():
    from flask import session
    session['current_generated_files'] = []
    os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)
    print("🔍 收到原始请求数据:", request.get_data(as_text=True))
    print("🔍 解析后的 JSON:", request.json)
    
    data = request.json
    uploaded_filename = data.get('filename')
    main_prompt = data.get('main_prompt')
    variant_prompt = data.get('variant_prompt')
    platform = data.get('platform', 'amazon')
    mode = data.get('mode', '6')

    if not uploaded_filename or not main_prompt or not variant_prompt:
        return jsonify({"error": "Missing parameters"}), 400

    if not uploaded_filename.startswith('http'):
        source_image_url = f"http://187.127.116.168:5000/uploads/{uploaded_filename}"
    else:
        source_image_url = uploaded_filename

    generated_images = []
    total_count = 25 if mode == '25' else 6
    main_count = 20 if mode == '25' else 1

    # 固定英文后缀，确保模型理解电商产品图需求
    if platform == 'amazon':
        suffix = "pure white background, no shadow, clean product photography, high detail, 8k"
    else:
        suffix = "clean light grey background, product photography, high quality"
    
    # 主图提示词：去掉中文指令，只保留产品描述+电商背景要求
    final_main_prompt = f"{main_prompt}, {suffix}"
    # 变体图提示词：去掉中文指令，只保留产品描述+高质量要求
    final_variant_prompt = f"{variant_prompt}, high quality, photorealistic product photography"

    for i in range(main_count):
        img_url = generate_image(final_main_prompt, source_image_url)
        if img_url:
            try:
                print(f"开始下载主图: {img_url}")
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    saved_name = f"main_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    print(f"主图保存成功: {save_path}")
                    session['current_generated_files'].append(save_path)
                    generated_images.append({
                        "url": f"/generated_images/{saved_name}",
                        "prompt": final_main_prompt
                    })
            except Exception as e:
                print(f"下载主图失败: {e}")

    for i in range(5):
        img_url = generate_image(final_variant_prompt, source_image_url)
        if img_url:
            try:
                print(f"开始下载变体图: {img_url}")
                r = requests.get(img_url, timeout=30)
                if r.status_code == 200:
                    saved_name = f"variant_{i+1}_{uuid.uuid4().hex}.png"
                    save_path = os.path.join(app.config['GENERATED_FOLDER'], saved_name)
                    with open(save_path, 'wb') as f:
                        f.write(r.content)
                    print(f"变体图保存成功: {save_path}")
                    session['current_generated_files'].append(save_path)
                    
                    generated_images.append({
                        "id": saved_name,
                        "url": f"/generated_images/{saved_name}",
                        "prompt": final_variant_prompt
                    })
            except Exception as e:
                print(f"下载变体图失败: {e}")

    if not generated_images:
        return jsonify({"error": "Failed to generate any images. Check API Key or Source Image URL."}), 500

    safe_images = []
    for img in generated_images:
        if isinstance(img, dict) and 'url' in img:
            safe_images.append(img['url'])
        elif isinstance(img, str):
            safe_images.append(img)

    print("### 最终返回给前端的链接：", safe_images)
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
    import os
    import zipfile
    from io import BytesIO
    from flask import make_response, send_file, session

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
