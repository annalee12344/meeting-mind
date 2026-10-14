# Meeting Mind 🧠 — Trợ Lý Trí Tuệ Cuộc Họp Tiếng Việt

**Meeting Mind** là nền tảng AI phân tích biên bản cuộc họp tiếng Việt chuyên sâu, giúp tự động trích xuất các quyết định đã chốt, danh sách việc cần làm (action items), các điểm thảo luận còn bỏ ngỏ và những vướng mắc rào cản từ bản ghi chép cuộc họp thô.

---

## 🌟 Tính Năng Nổi Bật

- **4 Nhóm Thông Tin Phân Định Rõ Ràng:**
  - 🎯 **Quyết định (Decisions):** Ghi nhận các thỏa thuận chính thức kèm tiến trình thay đổi quyết định (*Decision Trail*).
  - 📋 **Việc cần làm (Tasks):** Tự động phân công người phụ trách, thời hạn chót chuẩn hóa (ISO 8601), phân tách rõ vai trò (người giao, người làm, bên phụ thuộc bên ngoài).
  - ❓ **Điểm chưa chốt (Unresolved):** Ghi nhận các đề xuất chưa đạt được đồng thuận hoặc việc chưa có người nhận.
  - 🚧 **Vướng mắc (Issues / Blockers):** Phát hiện các rào cản kỹ thuật hoặc phụ thuộc bên ngoài kèm hệ thống ghi chú thảo luận (*Issue Notes*).
- **Khử Trùng Lặp Thông Minh (Multi-Turn Task Deduplication):** Hợp nhất các tác vụ được nhắc lại qua nhiều lượt thoại khác nhau mà vẫn giữ nguyên bằng chứng và thời hạn chót chuẩn nhất.
- **Xác Thực Bằng Chứng Chặt Chẽ (Evidence Spotlight):** Mỗi thông tin trích xuất đều có trích dẫn lời phát biểu nguyên văn của người tham dự để đối soát tức thì trong biên bản.
- **Lớp Dữ Liệu Kết Hợp (AI + User Overlay):** Cho phép người dùng chỉnh sửa, đánh dấu hoàn thành, thêm việc thủ công mà không làm mất kết quả AI gốc; lưu trữ an toàn qua `PersistenceAdapter`.
- **Giao Diện Hiện Đại & Tinh Gọn:** Xây dựng trên React 19, Tailwind CSS v4, Radix UI và cô lập lỗi với Error Boundary chống văng trang.

---

## 🏗️ Kiến Trúc Hệ Thống

```
meeting-mind/
├── models/                  # Pydantic schemas (Step 2 internal & Step 4 public models)
├── pipeline/                # 4-stage analysis engine
│   ├── preprocessor.py      # Tiền xử lý văn bản, đánh mã utterance
│   ├── extractor.py         # Step 1: Trích xuất phát biểu thô qua Gemini API
│   ├── resolver.py          # Step 2: Giải quyết quyết định, khử trùng lặp task
│   ├── validator.py         # Step 3: Fuzzy matching xác thực bằng chứng
│   ├── mapper.py            # Step 4: Chuẩn hóa deadline & phân nhóm public
│   ├── job_store.py         # Quản lý hàng đợi và tiến trình job nền (in-memory)
│   └── llm_client.py        # Wrapper Google Gemini API với retry & structured output
├── server.py                # FastAPI backend server với RESTful API & CORS
├── config.py                # Quản lý cấu hình môi trường (.env)
├── render.yaml              # Cấu hình tự động deploy backend lên Render.com
└── meeting-muse-56/         # Frontend React 19 + TypeScript + Vite + Tailwind CSS v4
    ├── src/components/      # UI components (Workspace, DecisionTrail, IssueNotes, TranscriptPanel)
    ├── src/lib/             # Merge engine, overlay store, API client, deadline logic
    └── src/routes/          # TanStack Router routes
```

---

## 🚀 Hướng Dẫn Chạy Cục Bộ (Local Development)

### 1. Chuẩn Bị Môi Trường
- **Python:** 3.11 trở lên
- **Node.js:** 20 trở lên
- **Google Gemini API Key:** Đăng ký miễn phí tại [Google AI Studio](https://aistudio.google.com/apikey).

---

### 2. Khởi Động Backend (FastAPI)

```bash
# 1. Di chuyển vào thư mục gốc dự án
cd meeting-mind

# 2. Tạo và kích hoạt môi trường ảo Python
python -m venv .venv
# Trên Windows:
.venv\Scripts\activate
# Trên Linux/macOS:
source .venv/bin/activate

# 3. Cài đặt các thư viện cần thiết
pip install -r requirements.txt

# 4. Thiết lập biến môi trường
cp .env.example .env
# Mở file .env và điền GEMINI_API_KEY của bạn:
# GEMINI_API_KEY=AIzaSy...

# 5. Khởi động API Server
uvicorn server:app --reload --port 8000
```
Backend API sẽ hoạt động tại: `http://localhost:8000` (Tài liệu API Swagger UI tại `http://localhost:8000/docs`).

---

### 3. Khởi Động Frontend (React 19)

Mở một cửa sổ terminal mới:

```bash
# 1. Di chuyển vào thư mục frontend
cd meeting-mind/meeting-muse-56

# 2. Cài đặt các package npm
npm install

# 3. Tạo file biến môi trường (nếu chưa có)
cp .env.example .env
# VITE_API_BASE_URL=http://localhost:8000

# 4. Chạy môi trường phát triển
npm run dev
```
Giao diện ứng dụng sẽ mở tại: `http://localhost:5173` (hoặc cổng hiển thị trên terminal).

---

## 🧪 Kiểm Thử (Testing)

Dự án có độ phủ kiểm thử toàn diện cho cả Backend và Frontend:

```bash
# Chạy toàn bộ 120 test backend:
python -m unittest discover -s tests

# Chạy bộ benchmark đánh giá 9 kịch bản phân tích mẫu:
python -m tests.test_runner --all --mock

# Chạy toàn bộ 46 test frontend (Vitest):
cd meeting-muse-56
npm test
```

---

## 🌐 Hướng Dẫn Deploy Public Miễn Phí 100%

Ứng dụng được thiết kế tối ưu để deploy hoàn toàn **MIỄN PHÍ** theo mô hình:
- **Backend (API):** Host trên [Render.com](https://render.com) (Free Web Service)
- **Frontend (Web UI):** Host trên [Vercel](https://vercel.com) (Free Tier)

### Bước 1: Đẩy mã nguồn lên GitHub của bạn
1. Tạo một repository mới trên GitHub (chế độ **Public**).
2. Đẩy toàn bộ source code của bạn lên:
```bash
git remote add origin https://github.com/<tai-khoan-cua-ban>/meeting-mind.git
git branch -M main
git push -u origin main
```

---

### Bước 2: Deploy Backend lên Render.com (Miễn Phí)
1. Truy cập [Render.com](https://render.com) và đăng nhập bằng tài khoản GitHub.
2. Nhấp **New +** -> Chọn **Web Service**.
3. Chọn repository `meeting-mind` của bạn.
4. Cấu hình thông số như sau:
   - **Name:** `meeting-mind-api` (hoặc tên tùy thích)
   - **Region:** `Singapore` (hoặc khu vực gần bạn nhất)
   - **Branch:** `main` (hoặc `master`)
   - **Root Directory:** *(Để trống)*
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** `Free` (512 MB RAM)
5. Kéo xuống mục **Environment Variables** và thêm 2 biến:
   - `GEMINI_API_KEY`: *(Nhập API Key Gemini của bạn)*
   - `CORS_ORIGINS`: `*`
6. Nhấp **Create Web Service**.
7. Chờ 1-2 phút cho Render build xong. Bạn sẽ nhận được đường dẫn API có dạng:
   👉 `https://meeting-mind-api.onrender.com`

---

### Bước 3: Deploy Frontend lên Vercel (Miễn Phí)
1. Truy cập [Vercel.com](https://vercel.com) và đăng nhập bằng tài khoản GitHub.
2. Nhấp **Add New...** -> Chọn **Project**.
3. Chọn repository `meeting-mind` của bạn từ danh sách.
4. Tại màn hình **Configure Project**:
   - **Framework Preset:** `Vite` (hoặc `Other`)
   - **Root Directory:** Nhấp **Edit** và chọn thư mục: `meeting-muse-56`
   - **Build Command:** `npm run build`
   - **Output Directory:** `.vercel/output` *(hoặc để mặc định theo framework)*
5. Mở mục **Environment Variables** và thêm:
   - **Name:** `VITE_API_BASE_URL`
   - **Value:** `https://meeting-mind-api.onrender.com` *(Link backend vừa tạo ở Bước 2)*
6. Nhấp nút **Deploy**.
7. Sau 1 phút, Vercel sẽ cung cấp tên miền public của bạn (ví dụ: `https://meeting-mind.vercel.app`).

> 🎉 **Hoàn tất!** Giờ đây bạn đã có một ứng dụng web public hoàn chỉnh, tốc độ cao, hỗ trợ phân tích biên bản cuộc họp tiếng Việt thông minh 24/7.

---

## 🔒 Bảo Mật & Lưu Ý Quan Trọng

- File `.env` chứa `GEMINI_API_KEY` đã được đưa vào `.gitignore` để không bao giờ bị đẩy lên GitHub công khai.
- Khi deploy lên Render, hãy nhập API Key vào phần Environment Variables trên bảng điều khiển của Render.
- Hệ thống hỗ trợ xử lý mượt mà 5 mẫu transcript benchmark tích hợp sẵn ngay cả khi chưa kết nối API key thực tế.

---

## 📄 Bản Quyền (License)

Dự án được phân phối dưới giấy phép MIT License.
