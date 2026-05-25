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

## 3) Cac buoc setup server Linux VPS (non-Docker)
1. Chuan bi VPS Linux (khuyen nghi Ubuntu 22.04 LTS), cau hinh SSH key.
2. Cap nhat he thong va cai goi can thiet: Python, venv, PostgreSQL, git, build dependencies.
3. Tao user chay ung dung rieng, cap quyen thu muc project.
4. Clone source code vao thu muc deploy.
5. Tao virtual environment va cai dependencies tu requirements.
6. Tao database PostgreSQL, user DB va cap quyen.
7. Cau hinh bien moi truong production trong file env noi bo.
8. Chay migration Alembic de tao schema.
9. Tao systemd service cho bot chinh.
10. Tao them service hoac timer cho scheduler dinh ky neu tach tien trinh.
11. Bat auto-start service khi reboot va chay thu bang systemctl.
12. Thiet lap logrotate hoac chinh sach quan ly journal de tranh day dia.
13. Mo firewall dung cong can thiet; neu dung webhook thi cau hinh them domain va HTTPS reverse proxy.
14. Neu uu tien trien khai nhanh trong 3 ngay, co the dung long polling de giam thoi gian setup ha tang HTTPS.

## 4) Cac buoc deploy san pham len server
1. Pre-deploy checklist: xac nhan backup DB, tag release, freeze dependency.
2. Pull source version moi len server.
3. Kich hoat venv va cai them dependency moi neu co.
4. Chay migration database.
5. Restart cac service systemd theo thu tu: API tich hop, bot worker, scheduler.
6. Chay health check: service status, log loi, kiem tra ket noi DB.
7. Smoke test nghiep vu chinh tren Telegram:
- /start, /mygoi, /giahan.
- Tao order va xac minh thanh toan.
- Cap quyen user sau thanh toan.
- Kiem tra lenh admin quan trong.
8. Theo doi log sau deploy toi thieu 1 den 2 gio.

## 5) Rollback khi co su co
1. Dung service lien quan.
2. Checkout lai ban release truoc.
3. Khoi phuc DB tu backup gan nhat neu migration gay loi du lieu.
4. Khoi dong lai service va chay smoke test toi thieu.
5. Ghi bien ban su co de cap nhat checklist lan deploy sau.

## 6) Checklist van hanh hang ngay
1. Kiem tra so don moi, don loi match va hang doi manual review.
2. Kiem tra job nhac han va kick han co chay dung lich.
3. Kiem tra dung luong log va trang thai service.
4. Kiem tra bao cao doanh thu daily va doi soat du lieu thanh toan.
