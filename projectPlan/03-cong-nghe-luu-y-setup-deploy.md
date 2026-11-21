## Cong nghe su dung, luu y ky thuat, setup server va deploy (khong Docker)

## 1) Cong nghe de xuat
1. Python 3.12.
2. Aiogram 3.x cho Telegram bot.
3. FastAPI cho endpoint noi bo va tich hop payment callback hoac polling service.
4. PostgreSQL 15+ cho du lieu giao dich va subscription.
5. SQLAlchemy + Alembic cho ORM va migration.
6. APScheduler cho tac vu nhac han va auto kick.
7. Uvicorn cho chay app service.
8. systemd cho quan ly tien trinh production.
9. logging theo chuan JSON hoac key-value de de truy vet.

## 2) Luu y ky thuat quan trong
1. Khong dung Docker trong moi truong production.
2. Chuan timezone co dinh Asia/Ho_Chi_Minh cho toan bo nghiep vu han dung.
3. Rule match thanh toan bat buoc: noi dung chuyen khoan co telegram_id + telegram_name + ma goi, dong thoi so tien phai khop.
4. Idempotency bat buoc cho event thanh toan de tranh cong han nhieu lan.
5. Tach quyen admin bang allowlist Telegram ID, khong dua vao username.
6. Moi action quan tri can ghi audit log.
7. Backup database truoc moi lan deploy.

## 3) Cai dat server tu dau (Ubuntu 22.04, non-Docker)

Hien trang production (cap nhat 21/11/2026): Ubuntu 22.04, 1 vCPU, 1 GB RAM, Python 3.12 (PPA deadsnakes),
PostgreSQL 14, user he thong `botuser` (home `/opt/telegrambot`), code tai `/opt/telegrambot/app-src`,
service systemd `telegrambot`. Bot chay 1 tien trinh duy nhat: long polling + APScheduler
(nhac han, kick, bao cao, va job `check_payments` xac nhan thanh toan). Khong can mo port, khong can HTTPS.

Tat ca lenh duoi chay bang `root`.

1. Goi he thong (font `fonts-dejavu-core` BAT BUOC: thieu font thi anh QR mat dong ten/STK/so tien):
```bash
apt update
apt install -y software-properties-common git postgresql fonts-dejavu-core
add-apt-repository -y ppa:deadsnakes/ppa
apt install -y python3.12 python3.12-venv
```
2. User chay ung dung va source code:
```bash
useradd --system --create-home --home-dir /opt/telegrambot --shell /bin/bash botuser
sudo -u botuser git clone https://github.com/tq-dat/TelegramBot-QrPayment.git /opt/telegrambot/app-src
cd /opt/telegrambot/app-src
sudo -u botuser python3.12 -m venv venv
sudo -u botuser venv/bin/pip install -r requirements.txt
```
3. Database (doi `MAT_KHAU` thanh mat khau manh):
```bash
sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'MAT_KHAU';"
sudo -u postgres psql -c "CREATE DATABASE telegrambot OWNER botuser;"
```
4. File cau hinh `.env` (khong commit, chi botuser doc duoc):
```bash
sudo -u botuser cp .env.example .env && chmod 600 .env
sudo -u botuser nano .env
```
   - `BOT_TOKEN`, `ADMIN_IDS` (Telegram user ID, cach nhau dau phay), `GROUP_ID`.
   - `DATABASE_URL=postgresql+asyncpg://botuser:MAT_KHAU@localhost:5432/telegrambot`
   - `BANK_*`, `SIEUTHICODE_API_URL`, `SIEUTHICODE_COOKIE`, `SIEUTHICODE_BANK_ID`.
   - `PAYMENT_POLL_INTERVAL_SECONDS=15` (chu ky job check_payments), `ORDER_EXPIRY_HOURS=24`
     (don con duoc tu xac nhan trong bao lau).
   - Moi admin trong `ADMIN_IDS` phai nhan /start cho bot 1 lan, neu khong bot khong nhan tin
     canh bao loi va don moi duoc.
5. Tao schema va kiem tra nhanh:
```bash
sudo -u botuser venv/bin/alembic upgrade head
sudo -u botuser venv/bin/python -m tests.test_payment_match
sudo -u botuser venv/bin/python -m tests.test_error_alert
```
6. Service systemd `/etc/systemd/system/telegrambot.service`:
```ini
[Unit]
Description=Telegram VIP Music Bot (aiogram long polling + scheduler)
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/opt/telegrambot/app-src
ExecStart=/opt/telegrambot/app-src/venv/bin/python /opt/telegrambot/app-src/main.py
Environment=PYTHONUNBUFFERED=1
Environment=LANG=C.UTF-8
Environment=LC_ALL=C.UTF-8
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/opt/telegrambot
StandardOutput=journal
StandardError=journal
SyslogIdentifier=telegrambot

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload
systemctl enable --now telegrambot
systemctl status telegrambot
```
7. Thu muc backup:
```bash
mkdir -p /opt/telegrambot/backups && chown botuser:botuser /opt/telegrambot/backups && chmod 700 /opt/telegrambot/backups
```
8. Luu y journal: mac dinh journald dung toi da ~10% dia cho TAT CA service; tren VPS 16 GB log
   cua bot chi con giu ~6 tuan. Neu can giu lau hon, cau hinh `SystemMaxUse` / `MaxRetentionSec`
   trong `/etc/systemd/journald.conf`.

## 4) Cap nhat ban moi (update ve sau)

Chay bang `root`. Thay `<nhanh>` bang nhanh can deploy (binh thuong la `main`).

1. Truoc khi deploy:
   - Doc commit / migration moi (`git log`, `alembic/versions/`).
   - Kiem tra don dang cho: job `check_payments` se chuyen moi don `pending` qua `ORDER_EXPIRY_HOURS`
     sang `expired` (khong nhan khach neu da qua han > 1 gio). Doi soat sao ke va "Confirm don" truoc
     neu nghi khach da tra.
```bash
sudo -u postgres psql -d telegrambot -c "select order_code,status,amount,created_at from orders where status='pending' order by created_at;"
```
2. Backup DB:
```bash
cd /opt/telegrambot/app-src
F=/opt/telegrambot/backups/telegrambot-$(date +%Y%m%d-%H%M)-pre-$(sudo -u botuser git rev-parse --short HEAD).sql.gz
sudo -u postgres pg_dump telegrambot | gzip > $F && chown botuser:botuser $F && chmod 600 $F && ls -la $F
```
3. Lay code moi + dependency (bot cu van dang chay, chua anh huong):
```bash
sudo -u botuser git fetch origin
sudo -u botuser git checkout <nhanh> && sudo -u botuser git pull --ff-only
sudo -u botuser venv/bin/pip install -r requirements.txt
```
4. Kiem tra truoc khi restart (that bai thi DUNG, khong restart):
```bash
sudo -u botuser venv/bin/python -m tests.test_payment_match
sudo -u botuser venv/bin/python -m tests.test_error_alert
sudo -u botuser venv/bin/python -c "import main"
```
5. Migration + restart:
```bash
sudo -u botuser venv/bin/alembic upgrade head
systemctl restart telegrambot
sleep 30; systemctl is-active telegrambot
```
6. Kiem tra sau deploy:
```bash
# Log ke tu khi restart (thay gio cho dung)
journalctl -u telegrambot --since "10 min ago" -o cat | grep -E '"levelname": "(ERROR|WARNING)"'
# Job thanh toan co goi sieuthicode thanh cong khong (chi goi khi co don dang cho)
journalctl -u telegrambot --since "10 min ago" -o cat | grep historyapi | grep -c "200 OK"
```
   - Luu y: log la JSON nen journald coi moi dong la muc info, `journalctl -p err` KHONG loc duoc;
     phai grep `"levelname": "ERROR"`.
   - Moi loi muc ERROR deu duoc bot nhan cho admin (toi da 1 lan / 30 phut moi loai loi).
7. Smoke test tren Telegram: /start, /mygoi, /giahan -> chon goi -> nhan anh QR day du chu;
   /admin -> "Don pending" thay don vua tao; huy don.
8. Theo doi log va tin canh bao admin it nhat 1-2 gio.

## 5) Rollback khi co su co
```bash
systemctl stop telegrambot
cd /opt/telegrambot/app-src
# 1. Ha migration ve revision cua ban cu NEU ban moi co migration (vd 004 -> 003)
sudo -u botuser venv/bin/alembic downgrade <revision_cu>
# 2. Ve commit cu (xem lai trong ten file backup: ...-pre-<commit>.sql.gz)
sudo -u botuser git checkout <commit_cu>
sudo -u botuser venv/bin/pip install -r requirements.txt
systemctl start telegrambot
```
- Chi khoi phuc DB tu backup khi migration lam hong du lieu (mat cac don/thanh toan phat sinh sau
  thoi diem backup):
```bash
systemctl stop telegrambot
sudo -u postgres dropdb telegrambot && sudo -u postgres createdb -O botuser telegrambot
zcat /opt/telegrambot/backups/<file>.sql.gz | sudo -u postgres psql -d telegrambot
systemctl start telegrambot
```
- Ghi bien ban su co de cap nhat checklist lan deploy sau.

## 5b) Lich su deploy
| Ngay | Commit | Noi dung | Ghi chu |
|---|---|---|---|
| 21/11/2026 | 4203f36 (nhanh `fix/payment-job`) | Job `check_payments` thay monitor tung don; render QR SVG->PNG; canh bao loi cho admin; migration 004 | Cai them `fonts-dejavu-core`. Backup: `telegrambot-20261121-1748-pre-4203f36.sql.gz`. 5 don pending cu (28/10-16/11) da tu chuyen `expired` khi khoi dong. Sau khi merge vao `main`, chuyen server ve `main`: `git checkout main && git pull --ff-only`. |

## 6) Checklist van hanh hang ngay
1. Kiem tra so don moi, don loi match va hang doi manual review (/admin -> "Don pending").
2. Kiem tra job nhac han va kick han co chay dung lich.
3. Kiem tra dung luong log va trang thai service.
4. Kiem tra bao cao doanh thu daily va doi soat du lieu thanh toan.
