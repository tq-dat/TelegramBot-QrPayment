## Testcase MVP - Telegram VIP Music Bot

Tai lieu nay mo ta testcase cho pham vi MVP 3 ngay, tap trung vao luong user, payment hybrid, admin panel Telegram, scheduler va report.

## 1. Scope
- In scope: command user, order lifecycle, auto payment monitor, admin manual actions, expiry reminder, auto kick, report daily weekly.
- Out of scope: DRM anti leak nang cao, web dashboard, automation refund policy phuc tap.

## 2. Moi truong test
- Python 3.12, PostgreSQL 15+.
- Bot da set env hop le: BOT_TOKEN, ADMIN_IDS, GROUP_ID, DB URL, bank settings, sieuthicode settings.
- Da chay migration.
- Co it nhat 2 account Telegram:
1. 1 admin account co user_id nam trong ADMIN_IDS.
2. 1 normal user account khong co quyen admin.

## 3. Quy uoc trang thai
- pending: don cho thanh toan.
- paid: don thanh toan thanh cong.
- expired: don qua han cho thanh toan.
- refunded: don duoc danh dau hoan tien.

## 4. Danh sach testcase

| ID | Scenario | Preconditions | Steps | Expected Result | Priority |
|---|---|---|---|---|---|
| TC-001 | /start voi user moi | User chua co trong DB | 1) User gui /start | User duoc tao trong DB, nhan welcome message | P0 |
| TC-002 | /start voi user bi ban | User is_banned = true | 1) User gui /start | Bot tra message BANNED, khong cho luong tiep | P0 |
| TC-003 | /help | Bot dang chay | 1) User gui /help | Bot tra help message dung format song ngu | P2 |
| TC-004 | /mygoi khi khong co goi active | User khong co subscription active | 1) User gui /mygoi | Bot thong bao chua co goi hoac da het han | P1 |
| TC-005 | /mygoi khi co goi active | User co subscription active | 1) User gui /mygoi | Bot hien plan, ngay het han, so ngay con lai | P0 |
| TC-010 | /giahan hien danh sach goi | Bot dang chay | 1) User gui /giahan | Bot hien keyboard chon 4 goi Basic Standard Premium Ultimate | P0 |
| TC-011 | Chon goi tao order pending | User dang o man hinh chon goi | 1) User bam 1 goi | Tao order pending, tao order_code, transfer_description dung format, hien huong dan thanh toan | P0 |
| TC-012 | Chon lai goi moi se huy pending cu | User da co 1 order pending | 1) User bam /giahan va chon goi khac | Order pending cu bi cancel, chi con 1 pending moi | P0 |
| TC-013 | Bam cancel o man thanh toan | User dang co pending va monitor task | 1) User bam nut cancel | Monitor task bi dung, pending orders bi cancel, bot gui message da huy | P0 |
| TC-014 | Tao order thi admin nhan canh bao | ADMIN_IDS co it nhat 1 ID hop le | 1) User tao order pending | Moi admin nhan thong bao don moi co user, plan, amount, order_code, transfer memo | P1 |
| TC-015 | Fallback text neu khong du config QR | Thieu SIEUTHICODE_API_URL hoac BANK_ACCOUNT_NUMBER | 1) User tao order | Bot hien text instructions thay vi gui QR image | P1 |
| TC-016 | Tao QR thanh cong khi du config | Du config bank + sieuthicode + bank id | 1) User tao order | Bot gui anh QR, caption co order_code va transfer_description | P1 |
| TC-020 | Auto monitor bo qua giao dich baseline | Co transaction cu truoc khi monitor start | 1) Bat dau monitor 2) Dua lai transaction cu | Khong match transaction cu, order van pending | P0 |
| TC-021 | Auto match thanh cong voi memo + amount | Co transaction moi IN dung memo va dung amount | 1) Tao order 2) Day transaction hop le | Order thanh paid, tao subscription, user nhan thong bao thanh cong | P0 |
| TC-022 | Khong match neu sai amount | Co transaction moi memo dung nhung amount sai | 1) Tao order 2) Day transaction sai amount | Order khong duoc paid | P0 |
| TC-023 | Het thoi gian cho thanh toan | Khong co transaction hop le trong watch window | 1) Tao order 2) Cho het PAYMENT_WATCH_SECONDS | Order chuyen expired, user nhan thong bao het han thanh toan | P0 |
| TC-024 | Idempotency khi monitor gap transaction lap | 1 order pending, transaction bi fetch lap | 1) Day cung 1 transaction nhieu lan | Chi kich hoat subscription 1 lan, khong cong han lap | P0 |
| TC-025 | Thanh toan thanh cong tao invite link | GROUP_ID hop le, bot co quyen tao invite | 1) Auto match thanh cong | User nhan invite link 1 lan, order luu invite_link | P1 |
| TC-026 | Loi tao invite link van thong bao paid | GROUP_ID sai hoac bot thieu quyen | 1) Auto match thanh cong | User van nhan message paid kem canh bao khong tao duoc link | P1 |
| TC-030 | User thuong khong vao duoc /admin | User khong nam trong ADMIN_IDS | 1) User gui /admin | Bot tra khong co quyen admin | P0 |
| TC-031 | Admin vao panel thanh cong | User la admin | 1) Admin gui /admin | Bot hien Admin Panel keyboard | P0 |
| TC-032 | Admin xem active members | Co it nhat 1 subscription active | 1) Admin bam Members | Bot hien danh sach toi da 30 member active | P1 |
| TC-033 | Admin xem pending orders | Co it nhat 1 order pending | 1) Admin bam Pending | Bot hien danh sach toi da 20 don pending | P1 |
| TC-034 | Admin confirm order pending thanh cong | Co 1 order pending hop le | 1) Admin chon Confirm 2) Nhap order_code | Order -> paid, tao subscription, ghi audit log, user duoc notify | P0 |
| TC-035 | Admin confirm order da paid bi chan | Co order status paid hoac refunded | 1) Admin confirm lai order do | Bot tu choi va thong bao status hien tai | P0 |
| TC-036 | Admin give days cho user dang active | User co subscription active | 1) Admin chon Give days 2) Nhap user_id days | expires_at duoc cong them, ghi audit log, user duoc notify | P0 |
| TC-037 | Admin give days cho user chua active | User co trong DB nhung khong co sub active | 1) Admin give days | Tao subscription plan gift, is_active true | P1 |
| TC-038 | Admin ban user | User ton tai trong DB | 1) Admin chon Ban 2) Nhap user_id reason | user.is_banned=true, co banned_reason, ghi audit log, co ban chat neu GROUP_ID co cau hinh | P0 |
| TC-039 | Admin refund note | Co order ton tai | 1) Admin chon Refund note 2) Nhap order_code note | order.status=refunded, order.note duoc luu, ghi audit log | P1 |
| TC-040 | Huy FSM trong admin panel | Admin dang o state bat ky | 1) Admin bam cancel FSM | State duoc clear, quay lai Admin Panel | P2 |
| TC-050 | Reminder D-3 gui 1 lan | Co sub active sap het han trong cua so D-3 | 1) Chay job reminder | User nhan thong bao D-3, d3_reminder_sent=true | P1 |
| TC-051 | Reminder D-1 gui 1 lan | Co sub active sap het han trong cua so D-1 | 1) Chay job reminder | User nhan thong bao D-1, d1_reminder_sent=true | P1 |
| TC-052 | Auto kick user het han | Co sub active expires_at <= now, GROUP_ID hop le | 1) Chay job kick | User bi ban+unban khoi group, sub.is_active=false | P0 |
| TC-053 | Notify user sau khi het han | Co sub het han | 1) Chay job kick | User nhan message membership expired va huong dan /giahan | P1 |
| TC-054 | Scheduler dang ky du job | Bot startup co scheduler | 1) Khoi dong bot 2) Kiem tra job list | Co expiry_reminders, kick_expired, report_daily, report_weekly | P1 |
| TC-060 | /baocao daily | Admin account | 1) Admin gui /baocao | Bot tra bao cao daily dung format HTML | P1 |
| TC-061 | /baocao weekly | Admin account | 1) Admin gui /baocao weekly | Bot tra bao cao weekly dung format HTML | P1 |
| TC-062 | Callback report tren admin panel | Admin account | 1) Bam bao cao hom nay 2) Bam bao cao tuan | Bot tra report tuong ung va hien lai Admin Panel | P1 |
| TC-063 | Noi dung report day du metric | Co du lieu paid expired refunded active | 1) Tao du lieu mau 2) Lay report | Report co tong doanh thu, so don thanh cong, refund, expired, active member, breakdown theo plan | P0 |
| TC-064 | Non-admin bi chan callback report | User thuong bam callback admin (gia lap) | 1) Goi callback adm_report_daily | Bot tu choi, khong tra report | P1 |
| TC-070 | Admin auth theo ID khong theo username | 2 user cung username khac ID | 1) User co username giong admin nhung ID khac gui /admin | User khong co quyen | P0 |
| TC-071 | GROUP_ID chua config | GROUP_ID rong | 1) Kich hoat thanh toan thanh cong | He thong khong crash, tra canh bao khong tao duoc invite | P1 |
| TC-072 | Restart service khong nhan doi scheduler | Khoi dong lai bot nhieu lan | 1) Restart service 2) Kiem tra job id | Moi job id replace_existing, khong tao duplicate jobs | P1 |
| TC-073 | Audit log cho action admin | Co action confirm give_days ban refund | 1) Chay tung action admin | Bang audit_logs co ban ghi day du admin_id, action, target_user_id, detail | P0 |

## 5. Test data de xai lai
- User A: normal user dung de tao don.
- User B: user bi ban.
- User C: user co sub active.
- User D: user het han.
- 1 order pending, 1 order paid, 1 order refunded, 1 order expired.

## 6. Tieu chi pass cho MVP
1. 100 phan tram testcase P0 pass.
2. It nhat 90 phan tram testcase P1 pass.
3. Khong co bug blocker o luong: tao order, confirm payment, cap quyen, auto kick, admin control.

## 7. Goi y uu tien automation
- Uu tien viet automated test cho P0 truoc.
- Mock Telegram API va sieuthicode API de test tinh huong bien.
- Chay smoke test manual tren Telegram that truoc khi go-live.
