## Ke hoach tong quat: Telegram VIP Music Bot (MVP 3 ngay)

Muc tieu la trien khai bot Telegram ban goi thanh vien VIP cho nhom nhac, quan tri hoan toan tren Telegram, tu dong hoa thanh toan theo mo hinh hybrid va van hanh production tren Linux VPS khong dung Docker.

## Muc tieu chinh
- Tu dong hoa mua goi, gia han, quan ly han dung.
- Nhac sap het han va tu dong xoa thanh vien khi het han.
- Quan tri vien thao tac toan bo tren Telegram: xem thanh vien, ban, tang ngay, xu ly refund.
- Co bao cao doanh thu theo ngay, tuan va theo yeu cau.

## Pham vi trien khai
- Bao gom:
1. User flow: /start, /mygoi, /giahan, /help.
2. 4 goi: Basic 30 ngay, Standard 60 ngay, Premium 90 ngay, Ultimate 365 ngay.
3. 1 private group voi 2 Topics co dinh: RAW va MINIMAL.
4. Payment verification hybrid: tu dong qua sieuthicode truoc, fallback manual cho admin khi can.
5. Vong doi goi: nhac D-3, D-1, het han thi kick.
6. Bao cao: tong don, tong tien, goi ban chay, so user moi.

- Chua bao gom trong moc 3 ngay:
1. Chong leak nang cao (DRM/watermark tu dong).
2. Dashboard web rieng.
3. Tu dong hoa refund theo rule phuc tap.

## Cach tiep can thuc hien
1. Phase 0: Chot dac ta, quyen bot, quyen admin, chuan noi dung thanh toan.
2. Phase 1: Dung nen tang backend va du lieu.
3. Phase 2: Hoan thien user flow va vong doi membership.
4. Phase 3: Tich hop payment hybrid va bo lenh admin Telegram.
5. Phase 4: Bao cao, kiem thu, trien khai production va go-live.

## Ket qua ban giao ky vong
1. Bot chay production on dinh tren Linux VPS non-Docker.
2. Toan bo luong mua gia han hoat dong end-to-end.
3. Admin co du cong cu van hanh tren Telegram.
4. Co checklist kiem thu, checklist deploy va checklist rollback.

## Rui ro chinh va giam thieu
1. Sai khop giao dich chuyen khoan: bat buoc rule noi dung chuyen khoan + so tien + idempotency.
2. Kick sai user hoac tre lich: scheduler chay theo timezone co dinh, co log kiem tra va retry.
3. Loi van hanh khi deploy gap: bat buoc backup truoc deploy, rollout theo checklist, co rollback nhanh.

## Tieu chi nghiem thu
1. User co the mua moi va gia han thanh cong.
2. Canh bao gan het han gui dung va user het han bi xoa khoi nhom.
3. Admin thao tac day du cac lenh quan tri tren Telegram.
4. Bao cao doanh thu tra dung so lieu tren du lieu test va staging.
