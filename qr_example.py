from config import (
    API_TOKEN,
    VNP_TMN_CODE,
    VNP_HASH_SECRET,
    VNP_URL,
    VNP_AMOUNT,
    VNP_RETURN_URL,
    API_HOST,
    API_PORT,
    SIEUTHICODE_ENABLED,
    SIEUTHICODE_BASE_URL,
    SIEUTHICODE_QR_PAGE,
    SIEUTHICODE_TIMEOUT,
    SIEUTHICODE_MAX_REFRESH_RETRY,
    VIETQR_IMAGE_TEMPLATE,
    SIEUTHICODE_AUTH_MODE,
    SIEUTHICODE_REQUEST_PHPSESSID,
    SIEUTHICODE_REQUEST_CF_CLEARANCE,
    SIEUTHICODE_BANK_ID,
    SIEUTHICODE_ACCOUNT_NO,
    SIEUTHICODE_ACCOUNT_NAME,
    SIEUTHICODE_AMOUNT,
    SIEUTHICODE_DEFAULT_MEMO,
    SIEUTHICODE_BROWSER_AUTH_ENABLED,
    SIEUTHICODE_BROWSER_HEADLESS,
    SIEUTHICODE_BROWSER_TIMEOUT_MS,
    SIEUTHICODE_USER_DATA_DIR,
    SIEUTHICODE_COOKIE_FILE,
    SIEUTHICODE_BROWSER_CHANNEL,
    SIEUTHICODE_BROWSER_IGNORE_AUTOMATION_FLAG,
    SIEUTHICODE_BROWSER_EXTRA_ARGS,
    SIEUTHICODE_LOGIN_MARKERS,
    SIEUTHICODE_GOOGLE_BLOCK_MARKERS,
    SIEUTHICODE_HISTORY_ENDPOINT_TEMPLATE,
    SIEUTHICODE_HISTORY_TOKEN,
    SIEUTHICODE_HISTORY_PHPSESSID,
    SIEUTHICODE_PAYMENT_WATCH_SECONDS,
    SIEUTHICODE_PAYMENT_POLL_INTERVAL_SECONDS,
    SIEUTHICODE_PAYMENT_REQUIRE_IN_TYPE,
    TELEGRAM_SUCCESS_GROUP_CHAT_ID,
    TELEGRAM_INVITE_LINK_TTL_SECONDS,
    TELEGRAM_INVITE_LINK_MEMBER_LIMIT,
)
import argparse
import telebot
import hmac
import hashlib
import uuid
import requests
import qrcode
import threading
import time
import unicodedata
from io import BytesIO
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import quote_plus
from flask import Flask, jsonify, request  # type: ignore[reportMissingImports]

from sieuthicode_auth_browser import SieuthicodeBrowserAuth
from sieuthicode_client import (
    SieuthicodeClientError,
    SieuthicodeManualLoginRequired,
    SieuthicodeQRClient,
)

bot = telebot.TeleBot(token=API_TOKEN)
app = Flask(__name__)
payment_results = {}
_sieuthicode_client: Optional[SieuthicodeQRClient] = None
pending_sieuthicode_payments: Dict[str, Dict[str, Any]] = {}
pending_sieuthicode_payments_lock = threading.Lock()


def _build_request_mode_cookies() -> Dict[str, str]:
    cookies: Dict[str, str] = {}

    php_sessid = (
        (SIEUTHICODE_REQUEST_PHPSESSID or "").strip()
        or (SIEUTHICODE_HISTORY_PHPSESSID or "").strip()
    )
    cf_clearance = (SIEUTHICODE_REQUEST_CF_CLEARANCE or "").strip()

    if php_sessid:
        cookies["PHPSESSID"] = php_sessid
    if cf_clearance:
        cookies["cf_clearance"] = cf_clearance

    return cookies


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").lower().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _collapse_spaces(value: str) -> str:
    return " ".join((value or "").split())


def _to_loose_text(value: str) -> str:
    normalized = _normalize_match_text(value)
    converted = "".join(
        ch if (ch.isalnum() or ch in {"_", " "}) else " "
        for ch in normalized
    )
    return _collapse_spaces(converted)


def _build_memo_candidates(memo: str) -> set[str]:
    candidates: set[str] = set()

    strict = _collapse_spaces(_normalize_match_text(memo))
    if strict:
        candidates.add(strict)

    without_at = _collapse_spaces(strict.replace("@", " "))
    if without_at:
        candidates.add(without_at)

    loose = _to_loose_text(memo)
    if loose:
        candidates.add(loose)

    tokens = without_at.split()
    if len(tokens) >= 2 and tokens[0].isdigit():
        candidates.add(tokens[0])
        candidates.add(f"{tokens[0]} {tokens[1]}")

    return {item for item in candidates if item}


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _format_watch_window(seconds: int) -> str:
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} phút"
    return f"{seconds} giây"


def _resolve_group_chat_id(raw_chat_id: str) -> Optional[Any]:
    value = (raw_chat_id or "").strip()
    if not value:
        return None

    if value.startswith("-") and value[1:].isdigit():
        return int(value)
    if value.isdigit():
        return int(value)
    return value


def _create_single_use_group_invite(payment_id: str) -> tuple[Optional[str], Optional[str]]:
    chat_id = _resolve_group_chat_id(TELEGRAM_SUCCESS_GROUP_CHAT_ID)
    if chat_id is None:
        return None, "Chua cau hinh TELEGRAM_SUCCESS_GROUP_CHAT_ID trong config.py"

    expire_at = datetime.now() + timedelta(seconds=TELEGRAM_INVITE_LINK_TTL_SECONDS)
    try:
        invite = bot.create_chat_invite_link(
            chat_id=chat_id,
            expire_date=int(expire_at.timestamp()),
            member_limit=TELEGRAM_INVITE_LINK_MEMBER_LIMIT,
            name=f"pay-{payment_id}",
        )
    except Exception as exc:
        return None, f"Khong tao duoc link moi: {exc}"

    invite_link = getattr(invite, "invite_link", None)
    if not invite_link:
        return None, "Khong nhan duoc invite_link tu Telegram API"
    return str(invite_link), None


def _require_history_token() -> str:
    token = (SIEUTHICODE_HISTORY_TOKEN or "").strip()
    if not token:
        raise SieuthicodeClientError("Thieu SIEUTHICODE_HISTORY_TOKEN trong config.py")
    return token


def _create_vietqr_image(memo: str) -> BytesIO:
    url = VIETQR_IMAGE_TEMPLATE.format(
        bank_id=SIEUTHICODE_BANK_ID,
        account_no=SIEUTHICODE_ACCOUNT_NO,
    )
    query = (
        f"amount={SIEUTHICODE_AMOUNT}"
        f"&addInfo={quote_plus(memo)}"
        f"&accountName={quote_plus(SIEUTHICODE_ACCOUNT_NAME)}"
    )
    response = requests.get(f"{url}?{query}", timeout=SIEUTHICODE_TIMEOUT)
    response.raise_for_status()

    buf = BytesIO(response.content)
    buf.seek(0)
    return buf


def _fetch_sieuthicode_transactions() -> list[dict[str, Any]]:
    return _get_sieuthicode_client().get_transaction_history(
        endpoint_template=SIEUTHICODE_HISTORY_ENDPOINT_TEMPLATE,
        token=_require_history_token(),
        php_sessid=(SIEUTHICODE_HISTORY_PHPSESSID or None),
    )


def _snapshot_transaction_ids(transactions: list[dict[str, Any]]) -> set[str]:
    txn_ids: set[str] = set()
    for tx in transactions:
        tx_id = str(tx.get("transactionID", "")).strip()
        if tx_id:
            txn_ids.add(tx_id)
    return txn_ids


def _create_pending_payment(chat_id: int, memo: str, amount: int) -> str:
    _require_history_token()

    payment_id = uuid.uuid4().hex[:12]
    created_at = datetime.now()
    expires_at = created_at + timedelta(seconds=SIEUTHICODE_PAYMENT_WATCH_SECONDS)

    baseline_ids: set[str] = set()
    try:
        baseline_ids = _snapshot_transaction_ids(_fetch_sieuthicode_transactions())
    except Exception:
        # Baseline errors should not block QR generation; watcher will keep polling.
        baseline_ids = set()

    with pending_sieuthicode_payments_lock:
        pending_sieuthicode_payments[payment_id] = {
            "payment_id": payment_id,
            "chat_id": chat_id,
            "memo": memo,
            "amount": amount,
            "status": "pending",
            "created_at": created_at,
            "expires_at": expires_at,
            "updated_at": created_at,
            "baseline_ids": baseline_ids,
            "matched_transaction": None,
            "invite_link": None,
            "error": None,
        }

    return payment_id


def _serialize_pending_payment(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "payment_id": payload.get("payment_id"),
        "chat_id": payload.get("chat_id"),
        "memo": payload.get("memo"),
        "amount": payload.get("amount"),
        "status": payload.get("status"),
        "created_at": payload.get("created_at").isoformat() if payload.get("created_at") else None,
        "expires_at": payload.get("expires_at").isoformat() if payload.get("expires_at") else None,
        "updated_at": payload.get("updated_at").isoformat() if payload.get("updated_at") else None,
        "matched_transaction": payload.get("matched_transaction"),
        "invite_link": payload.get("invite_link"),
        "error": payload.get("error"),
    }


def _set_pending_payment_status(
    payment_id: str,
    *,
    status: str,
    matched_transaction: Optional[dict[str, Any]] = None,
    invite_link: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    with pending_sieuthicode_payments_lock:
        payload = pending_sieuthicode_payments.get(payment_id)
        if not payload:
            return None

        payload["status"] = status
        payload["updated_at"] = datetime.now()
        payload["error"] = error
        if matched_transaction is not None:
            payload["matched_transaction"] = matched_transaction
        if invite_link is not None:
            payload["invite_link"] = invite_link
        return dict(payload)


def _find_matching_transaction(
    transactions: list[dict[str, Any]],
    *,
    memo: str,
    amount: int,
    baseline_ids: set[str],
) -> Optional[dict[str, Any]]:
    memo_candidates = _build_memo_candidates(memo)

    for tx in transactions:
        tx_id = str(tx.get("transactionID", "")).strip()
        if tx_id and tx_id in baseline_ids:
            continue

        tx_amount = _to_int(tx.get("amount"))
        if tx_amount != amount:
            continue

        tx_type = _normalize_match_text(tx.get("type", ""))
        if SIEUTHICODE_PAYMENT_REQUIRE_IN_TYPE and tx_type and tx_type != "in":
            continue

        description_raw = str(tx.get("description", "") or "")
        description_strict = _collapse_spaces(_normalize_match_text(description_raw))
        description_loose = _to_loose_text(description_raw)

        if any(
            candidate in description_strict or candidate in description_loose
            for candidate in memo_candidates
        ):
            return tx

    return None


def _monitor_pending_payment(payment_id: str) -> None:
    while True:
        with pending_sieuthicode_payments_lock:
            payload = pending_sieuthicode_payments.get(payment_id)
            if not payload:
                return

            status = payload.get("status")
            if status != "pending":
                return

            chat_id = int(payload.get("chat_id"))
            memo = str(payload.get("memo", ""))
            amount = int(payload.get("amount", 0))
            expires_at = payload.get("expires_at")
            baseline_ids = set(payload.get("baseline_ids", set()))

        if not isinstance(expires_at, datetime):
            _set_pending_payment_status(payment_id, status="expired", error="Thieu du lieu han thanh toan")
            bot.send_message(chat_id, "❌ Đã quá hạn thời gian thanh toán")
            return

        if datetime.now() >= expires_at:
            _set_pending_payment_status(payment_id, status="expired")
            bot.send_message(chat_id, "❌ Đã quá hạn thời gian thanh toán")
            return

        try:
            transactions = _fetch_sieuthicode_transactions()
        except SieuthicodeManualLoginRequired:
            _set_pending_payment_status(
                payment_id,
                status="auth_expired",
                error="Phiên đăng nhập hết hạn khi kiểm tra giao dịch",
            )
            bot.send_message(
                chat_id,
                "❌ Phiên đăng nhập đã hết hạn khi kiểm tra thanh toán. Hãy chạy: python main.py --bootstrap-google",
            )
            return
        except Exception as exc:
            _set_pending_payment_status(
                payment_id,
                status="pending",
                error=f"Loi tam thoi khi kiem tra giao dich: {exc}",
            )
            time.sleep(SIEUTHICODE_PAYMENT_POLL_INTERVAL_SECONDS)
            continue

        matched = _find_matching_transaction(
            transactions,
            memo=memo,
            amount=amount,
            baseline_ids=baseline_ids,
        )

        if matched:
            invite_link, invite_error = _create_single_use_group_invite(payment_id)
            _set_pending_payment_status(
                payment_id,
                status="success",
                matched_transaction=matched,
                invite_link=invite_link,
                error=invite_error,
            )

            success_message = (
                "✅ Thanh toán thành công\n"
                f"🧾 Mã theo dõi: {payment_id}\n"
                f"💵 Số tiền: {amount:,} VND"
            )

            if invite_link:
                success_message += (
                    "\n🔗 Link mời vào nhóm (dùng 1 lần, hiệu lực 5 phút):\n"
                    f"{invite_link}"
                )
            else:
                success_message += (
                    "\n⚠️ Đã xác nhận thanh toán nhưng chưa tạo được link mời nhóm."
                )

            bot.send_message(
                chat_id,
                success_message,
            )
            return

        time.sleep(SIEUTHICODE_PAYMENT_POLL_INTERVAL_SECONDS)


def _get_sieuthicode_client() -> SieuthicodeQRClient:
    global _sieuthicode_client

    if _sieuthicode_client is None:
        auth_mode = (SIEUTHICODE_AUTH_MODE or "browser").strip().lower()
        if auth_mode not in {"browser", "requests"}:
            auth_mode = "browser"

        request_mode_cookies = _build_request_mode_cookies()
        browser_auth = None
        browser_auth_enabled = auth_mode == "browser" and SIEUTHICODE_BROWSER_AUTH_ENABLED

        if browser_auth_enabled:
            browser_auth = SieuthicodeBrowserAuth(
                base_url=SIEUTHICODE_BASE_URL,
                qr_page_path=SIEUTHICODE_QR_PAGE,
                user_data_dir=SIEUTHICODE_USER_DATA_DIR,
                cookie_file=SIEUTHICODE_COOKIE_FILE,
                headless=SIEUTHICODE_BROWSER_HEADLESS,
                timeout_ms=SIEUTHICODE_BROWSER_TIMEOUT_MS,
                login_markers=SIEUTHICODE_LOGIN_MARKERS,
                browser_channel=SIEUTHICODE_BROWSER_CHANNEL,
                ignore_automation_flag=SIEUTHICODE_BROWSER_IGNORE_AUTOMATION_FLAG,
                browser_extra_args=SIEUTHICODE_BROWSER_EXTRA_ARGS,
                google_block_markers=SIEUTHICODE_GOOGLE_BLOCK_MARKERS,
            )

        _sieuthicode_client = SieuthicodeQRClient(
            base_url=SIEUTHICODE_BASE_URL,
            timeout=SIEUTHICODE_TIMEOUT,
            cookie_file=SIEUTHICODE_COOKIE_FILE,
            max_refresh_retry=SIEUTHICODE_MAX_REFRESH_RETRY,
            login_markers=SIEUTHICODE_LOGIN_MARKERS,
            auth_mode=auth_mode,
            manual_cookies=request_mode_cookies,
            browser_auth_enabled=browser_auth_enabled,
            browser_auth=browser_auth,
        )

    return _sieuthicode_client


def bootstrap_sieuthicode_google_login() -> None:
    if not SIEUTHICODE_ENABLED:
        raise SieuthicodeClientError("Sieuthicode mode dang tat trong config")
    _get_sieuthicode_client().bootstrap_google_login()


def _build_hash_data(params, url_encode=True):
    sorted_params = sorted(params.items())
    if url_encode:
        return "&".join(
            f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in sorted_params
        )
    return "&".join(f"{k}={v}" for k, v in sorted_params)


def _sign_params(params, url_encode=True):
    hash_data = _build_hash_data(params, url_encode=url_encode)
    secure_hash = hmac.new(
        VNP_HASH_SECRET.encode("utf-8"),
        hash_data.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    signed_params = dict(params)
    signed_params["vnp_SecureHash"] = secure_hash
    return signed_params


def _call_vnpay(params):
    response = requests.get(VNP_URL, params=params, timeout=20)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise Exception("VNPay trả dữ liệu không phải JSON") from exc


def _verify_vnpay_signature(vnp_params):
    data = dict(vnp_params)
    received_hash = data.pop("vnp_SecureHash", "")
    data.pop("vnp_SecureHashType", None)
    if not received_hash:
        return False

    expected_hash = _sign_params(data, url_encode=True)["vnp_SecureHash"]
    return hmac.compare_digest(expected_hash, received_hash)


def _normalize_amount(amount_value):
    if amount_value and amount_value.isdigit():
        return int(amount_value) // 100
    return amount_value


def _build_payment_result(vnp_params, signature_valid):
    return {
        "txn_ref": vnp_params.get("vnp_TxnRef"),
        "amount": _normalize_amount(vnp_params.get("vnp_Amount")),
        "response_code": vnp_params.get("vnp_ResponseCode"),
        "transaction_status": vnp_params.get("vnp_TransactionStatus"),
        "bank_code": vnp_params.get("vnp_BankCode"),
        "pay_date": vnp_params.get("vnp_PayDate"),
        "order_info": vnp_params.get("vnp_OrderInfo"),
        "signature_valid": signature_valid,
        "success": signature_valid
        and vnp_params.get("vnp_ResponseCode") == "00"
        and vnp_params.get("vnp_TransactionStatus") == "00",
        "raw": vnp_params,
    }


@app.get("/api/vnpay/callback")
def vnpay_callback():
    vnp_params = {k: v for k, v in request.args.items() if k.startswith("vnp_")}
    if not vnp_params:
        return jsonify({"message": "Thiếu tham số vnp_*"}), 400

    signature_valid = _verify_vnpay_signature(vnp_params)
    result = _build_payment_result(vnp_params, signature_valid)

    txn_ref = result.get("txn_ref") or "unknown"
    payment_results[txn_ref] = result

    status_code = 200 if signature_valid else 400
    return jsonify(result), status_code


@app.get("/api/vnpay/ipn")
def vnpay_ipn():
    vnp_params = {k: v for k, v in request.args.items() if k.startswith("vnp_")}
    if not vnp_params:
        return jsonify({"RspCode": "99", "Message": "Invalid request"}), 400

    signature_valid = _verify_vnpay_signature(vnp_params)
    if not signature_valid:
        return jsonify({"RspCode": "97", "Message": "Invalid signature"}), 400

    result = _build_payment_result(vnp_params, signature_valid)
    txn_ref = result.get("txn_ref")
    if not txn_ref:
        return jsonify({"RspCode": "01", "Message": "Order not found"}), 400

    payment_results[txn_ref] = result
    return jsonify({"RspCode": "00", "Message": "Confirm Success"})


@app.get("/api/vnpay/result/<txn_ref>")
def get_vnpay_result(txn_ref):
    result = payment_results.get(txn_ref)
    if not result:
        return jsonify({"message": "Không tìm thấy giao dịch"}), 404
    return jsonify(result)


@app.get("/api/sieuthicode/payment-status/<payment_id>")
def get_sieuthicode_payment_status(payment_id):
    with pending_sieuthicode_payments_lock:
        payload = pending_sieuthicode_payments.get(payment_id)

    if not payload:
        return jsonify({"message": "Không tìm thấy phiên thanh toán"}), 404

    return jsonify(_serialize_pending_payment(payload))


def run_callback_api():
    app.run(host=API_HOST, port=API_PORT, debug=False, use_reloader=False)


def create_vnpay_qr():
    now = datetime.now()
    expire = now + timedelta(minutes=15)

    params = {
        "vnp_Version": "2.1.0",
        "vnp_Command": "genqr",
        "vnp_TmnCode": VNP_TMN_CODE,
        "vnp_Amount": str(VNP_AMOUNT * 100),
        "vnp_CurrCode": "VND",
        "vnp_TxnRef": uuid.uuid4().hex[:12],
        "vnp_OrderInfo": "Thanh toan don hang",
        "vnp_OrderType": "other",
        "vnp_Locale": "vn",
        "vnp_ReturnUrl": VNP_RETURN_URL,
        "vnp_IpAddr": "127.0.0.1",
        "vnp_CreateDate": now.strftime("%Y%m%d%H%M%S"),
        "vnp_ExpireDate": expire.strftime("%Y%m%d%H%M%S"),
    }

    signed_params = _sign_params(params, url_encode=True)
    data = _call_vnpay(signed_params)

    # Some QR APIs still validate signature with raw key=value concatenation.
    if data.get("code") == "97":
        signed_params = _sign_params(params, url_encode=False)
        data = _call_vnpay(signed_params)

    if data.get("code") == "00" and data.get("qrcontent"):
        qr_img = qrcode.make(data["qrcontent"])
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    else:
        raise Exception(f"VNPay lỗi: {data.get('message', 'Không rõ lỗi')} (code: {data.get('code')})")


def create_sieuthicode_qr(memo: Optional[str] = None):
    if not SIEUTHICODE_ENABLED:
        raise SieuthicodeClientError("Sieuthicode mode dang tat trong config")

    resolved_memo = memo or SIEUTHICODE_DEFAULT_MEMO
    return _create_vietqr_image(resolved_memo)


def build_telegram_transfer_memo(message) -> str:
    user = getattr(message, "from_user", None)
    if user is None:
        return SIEUTHICODE_DEFAULT_MEMO

    user_id = getattr(user, "id", None)
    username = (getattr(user, "username", "") or "").strip()
    if user_id and username:
        return f"{user_id} {username}"

    first_name = (getattr(user, "first_name", "") or "").strip()
    last_name = (getattr(user, "last_name", "") or "").strip()
    display_name = f"{first_name} {last_name}".strip()

    if user_id and display_name:
        return f"{user_id} {display_name}"
    if user_id:
        return str(user_id)
    if display_name:
        return display_name
    return SIEUTHICODE_DEFAULT_MEMO


@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "⏳ Đang tạo mã QR ...")
    try:
        watch_window_text = _format_watch_window(SIEUTHICODE_PAYMENT_WATCH_SECONDS)
        transfer_memo = build_telegram_transfer_memo(message)
        qr_buf = create_sieuthicode_qr(memo=transfer_memo)
        payment_id = _create_pending_payment(
            chat_id=message.chat.id,
            memo=transfer_memo,
            amount=SIEUTHICODE_AMOUNT,
        )

        bot.send_photo(
            message.chat.id,
            qr_buf,
            caption=(
                f"✅ Mã QR thanh toán {SIEUTHICODE_AMOUNT:,} VND\n"
                f"📝 Nội dung: {transfer_memo}\n"
                f"🧾 Mã theo dõi: {payment_id}\n"
                f"⏱ Theo dõi thanh toán trong {watch_window_text}"
            ),
        )

        threading.Thread(
            target=_monitor_pending_payment,
            args=(payment_id,),
            daemon=True,
        ).start()

        bot.send_message(
            message.chat.id,
            f"🔎 Hệ thống đang kiểm tra giao dịch. Nếu thanh toán trong {watch_window_text} sẽ tự báo thành công.",
        )
    except SieuthicodeManualLoginRequired:
        bot.send_message(
            message.chat.id,
            "❌ Phiên Google đã hết hạn. Hãy chạy: python main.py --bootstrap-google",
        )
    except SieuthicodeClientError as e:
        bot.send_message(message.chat.id, f"❌ Lỗi Sieuthicode: {str(e)}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Lỗi tạo mã QR: {str(e)}")


@bot.message_handler(commands=['vnpay'])
def welcome_vnpay(message):
    bot.send_message(message.chat.id, "⏳ Đang tạo mã QR VNPay...")
    try:
        qr_buf = create_vnpay_qr()
        bot.send_photo(
            message.chat.id,
            qr_buf,
            caption=f"✅ Mã QR thanh toán {VNP_AMOUNT:,} VND\n⏱ Hết hạn sau 15 phút",
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Lỗi tạo mã QR VNPay: {str(e)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bootstrap-google",
        action="store_true",
        help="Mo browser de dang nhap Google va luu cookie Sieuthicode",
    )
    args = parser.parse_args()

    if args.bootstrap_google:
        try:
            bootstrap_sieuthicode_google_login()
            print("Bootstrap Google login thanh cong. Ban co the chay bot binh thuong.")
        except Exception as exc:
            print(f"Bootstrap Google login that bai: {exc}")
        return

    threading.Thread(target=run_callback_api, daemon=True).start()
    bot.polling()


if __name__ == "__main__":
    main()