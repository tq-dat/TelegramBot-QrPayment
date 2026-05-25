# Telegram VIP Music Bot

Bot Telegram bán gói thành viên VIP cho nhóm nhạc, quản trị hoàn toàn trên Telegram.

## Yêu cầu hệ thống

- Python 3.12+
- PostgreSQL 15+

---

## 1. Cài PostgreSQL (lần đầu)

### Windows (dùng cho dev local)

1. Tải installer tại: https://www.postgresql.org/download/windows/
2. Chạy installer, ghi nhớ **password** của user `postgres`.
3. Sau khi cài xong, mở **SQL Shell (psql)** hoặc dùng terminal:

```powershell
# Tạo database
psql -U postgres -c "CREATE DATABASE telegrambot;"
```

4. Xác nhận kết nối hoạt động:
```powershell
psql -U postgres -d telegrambot -c "\dt"
```

### Ubuntu 22.04 (Linux VPS production)

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql

# Tạo user DB và database
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "CREATE DATABASE telegrambot OWNER botuser;"
```

---

## 2. Setup môi trường Python

```bash
# Tạo virtual environment
python -m venv venv

# Kích hoạt (Windows)
venv\Scripts\activate

# Kích hoạt (Linux)
source venv/bin/activate

# Cài dependencies
pip install -r requirements.txt
```

---

## 3. Cấu hình `.env`

```bash
cp .env.example .env
```

Chỉnh sửa `.env` và điền các giá trị thật:

| Biến | Mô tả |
|------|-------|
| `BOT_TOKEN` | Token từ @BotFather |
| `ADMIN_IDS` | Telegram user ID của admin, cách nhau bằng dấu phẩy |
| `GROUP_ID` | ID của private group (bắt đầu bằng -100...) |
| `TOPIC_RAW_ID` | Thread ID của topic RAW |
| `TOPIC_MINIMAL_ID` | Thread ID của topic MINIMAL |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/telegrambot` |
| `BANK_ACCOUNT_NUMBER` | Số tài khoản ngân hàng nhận tiền |
| `BANK_ACCOUNT_NAME` | Tên chủ tài khoản |
| `BANK_NAME` | Tên ngân hàng (ví dụ: Vietcombank) |
| `SIEUTHICODE_API_URL` | URL API lịch sử giao dịch từ sieuthicode.net |
| `SIEUTHICODE_COOKIE` | Cookie xác thực (PHPSESSID=...) |

---

## 4. Chạy migration database

```bash
# Áp dụng migration lần đầu
alembic upgrade head
```

---

## 5. Chạy bot

```bash
python main.py
```

---

## Cấu trúc thư mục

```
├── main.py                  # Entry point
├── alembic/                 # Migration files
│   └── versions/
│       └── 001_initial_schema.py
├── app/
│   ├── config.py            # Settings + định nghĩa 4 gói
│   ├── database.py          # Async SQLAlchemy engine
│   ├── middleware.py        # DB session middleware
│   ├── models/              # ORM models
│   │   ├── user.py
│   │   ├── order.py
│   │   ├── subscription.py
│   │   └── audit_log.py
│   ├── handlers/            # Aiogram route handlers
│   │   ├── start.py         # /start, /help
│   │   ├── membership.py    # /mygoi
│   │   └── renewal.py       # /giahan + tạo đơn
│   ├── keyboards/           # Inline keyboard builders
│   ├── messages/            # Bilingual message templates
│   └── utils/
│       ├── order.py         # Sinh mã đơn, format VND
│       └── user.py          # Upsert user vào DB
└── requirements.txt
```

---

## Nội dung chuyển khoản

Khi tạo đơn, bot sẽ sinh nội dung chuyển khoản theo format:

```
{telegram_id} {username} {order_code}
```

Ví dụ: `6560945590 rabbitNoBra VIPA1B2C3D4`

Hệ thống Day 2 sẽ tự động dò khớp `order_code` trong lịch sử giao dịch ngân hàng qua API sieuthicode.

---

## Lưu ý bảo mật

- **Không commit file `.env`** (đã có trong `.gitignore`).
- Admin được phân quyền bằng **Telegram user ID** (không dùng username).
- Mọi thao tác admin được ghi vào bảng `audit_logs`.
