## Danh sach task va thoi gian thuc hien (MVP 3 ngay)

Tong effort muc tieu: 24 gio lam viec, phan bo theo critical path de dam bao go-live trong 3 ngay.

## Day 1 (8 gio) - Nen tang va user flow co ban
1. Chot dac ta van hanh, quyen bot, admin IDs, format message song ngu: 1.5 gio.
2. Khoi tao project Python, cau hinh env, logging, cau truc module: 1.0 gio.
3. Thiet ke schema database va migration dau tien: 1.5 gio.
4. Implement command /start, /mygoi, /help va menu chon goi: 1.5 gio.
5. Implement /giahan, tao don pending, sinh ma chuyen khoan va huong dan thanh toan: 2.0 gio.
6. Smoke test luong user co ban: 0.5 gio.

## Day 2 (8 gio) - Payment hybrid va admin Telegram
1. Tich hop sieuthicode de auto verify giao dich theo rule da chot: 2.5 gio.
2. Co che manual fallback cho admin khi auto match loi: 1.5 gio.
3. Kich hoat goi khi paid, xu ly cong don gia han dung logic: 1.0 gio.
4. Scheduler nhac het han D-3, D-1 va auto kick khi het han: 1.5 gio.
5. Bo lenh admin: xem member, ban, tang ngay, refund note, canh bao don moi: 1.5 gio.

## Day 3 (8 gio) - Bao cao, deploy va go-live
1. Bao cao doanh thu daily, weekly, on-demand tren Telegram: 1.5 gio.
2. Test trong tam: payment matching, renewal, expiry, quyen admin: 2.0 gio.
3. Setup Linux VPS non-Docker (venv + systemd + PostgreSQL): 2.0 gio.
4. Deploy staging, smoke test, sua loi nhanh: 1.0 gio.
5. Go-live production, monitoring sau phat hanh, ban giao checklist: 1.5 gio.

## Task phu thuoc quan trong
1. Tich hop payment phu thuoc viec tao order chuan va quy tac noi dung chuyen khoan.
2. Luong cap quyen group/topic phu thuoc trang thai payment paid.
3. Scheduler kick phu thuoc du lieu subscription chuan va timezone dung.
4. Deploy production chi thuc hien sau khi test luong critical pass.

## Moc nghiem thu theo ngay
1. Ket thuc Day 1: tao duoc don pending va user nhin thay trang thai goi.
2. Ket thuc Day 2: payment auto/manual chay duoc, admin commands chay duoc.
3. Ket thuc Day 3: bao cao dung so lieu, deploy thanh cong, go-live on dinh.

## Du phong tien do
1. Du phong toi thieu 10 phan tram effort cua Day 3 de xu ly loi phat sinh luc tich hop that.
2. Neu thieu thoi gian, uu tien giu luong core: mua goi, gia han, nhac han, kick han, admin co ban.
