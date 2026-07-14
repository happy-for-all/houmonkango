# ============================================================
# 🌿 訪問看護ナビ（全国版） build.py
#
# 目的：
#   ① 厚労省CSV（jigyosho_130.csv）から全国47都道府県のデータを抽出
#   ② Colabリサーチ結果（specialty_result_kansai.json）と事業所番号で
#      突き合わせ、精神科対応・医療的ケア対応・小児対応・リハビリ特化の
#      タグを付与（現時点では関西6府県のみリサーチ済み）
#   ③ 都道府県別の軽量JSONファイルに分割して dist/ に出力
#
# 👑 2026-07-15 更新：関西限定 → 全国対応に拡張。
#   特化タグはリサーチ済みの関西6府県のみ意味のある値が入り、
#   それ以外の都道府県は「情報なし（null）」として安全に出力される
#   （既存のnull許容設計がそのまま活きるため、ロジック自体の変更は不要）。
# ============================================================


# ------------------------------------------------------------
# 1. ライブラリの読み込み
# ------------------------------------------------------------
import os
import re
import json
import shutil
import unicodedata
import pandas as pd


# ------------------------------------------------------------
# 2. 設定（プロジェクトに合わせて調整可能な定数）
# ------------------------------------------------------------
CSV_PATH = "jigyosho_130.csv"                          # 厚労省の公式データ（ルート直下）
SPECIALTY_JSON_PATH = "specialty_result_kansai.json"   # Colabリサーチ結果（現時点では関西のみ）
OUTPUT_DIR = "dist"

# 👑 変更済み（2026-07-15）：関西6府県のみ → 全国47都道府県に拡張
ALL_PREFECTURES = {
    "北海道": "hokkaido", "青森県": "aomori", "岩手県": "iwate", "宮城県": "miyagi",
    "秋田県": "akita", "山形県": "yamagata", "福島県": "fukushima", "茨城県": "ibaraki",
    "栃木県": "tochigi", "群馬県": "gunma", "埼玉県": "saitama", "千葉県": "chiba",
    "東京都": "tokyo", "神奈川県": "kanagawa", "新潟県": "niigata", "富山県": "toyama",
    "石川県": "ishikawa", "福井県": "fukui", "山梨県": "yamanashi", "長野県": "nagano",
    "岐阜県": "gifu", "静岡県": "shizuoka", "愛知県": "aichi", "三重県": "mie",
    "滋賀県": "shiga", "京都府": "kyoto", "大阪府": "osaka", "兵庫県": "hyogo",
    "奈良県": "nara", "和歌山県": "wakayama", "鳥取県": "tottori", "島根県": "shimane",
    "岡山県": "okayama", "広島県": "hiroshima", "山口県": "yamaguchi", "徳島県": "tokushima",
    "香川県": "kagawa", "愛媛県": "ehime", "高知県": "kochi", "福岡県": "fukuoka",
    "佐賀県": "saga", "長崎県": "nagasaki", "熊本県": "kumamoto", "大分県": "oita",
    "宮崎県": "miyazaki", "鹿児島県": "kagoshima", "沖縄県": "okinawa",
}

# 👑 New（2026-07-15追加）：特化タグ（精神科対応等）のColabリサーチが
# 完了している都道府県のみを明記する。フロント側で「この地域は特化情報が
# まだありません」という注意書きの出し分けに使う。
SPECIALTY_RESEARCHED_PREFECTURES = ["osaka", "kyoto", "hyogo", "nara", "shiga", "wakayama"]

# CSVの更新時点（厚労省ページの表記に合わせて手動で更新してください）
CSV_SOURCE_LABEL = "2025年12月末時点（厚労省公表）"


# ------------------------------------------------------------
# 3. CSV読み込み（文字コード自動判定）
# ------------------------------------------------------------
def load_csv_with_encoding_fallback(path):
    """
    複数の文字コードを順に試し、読み込めたものを採用する。
    jigyosho_130.csvは基本的にutf-8-sigだが、万一の文字コード違いに
    備えて防御的な実装にしておく。
    """
    encodings_to_try = ["utf-8-sig", "utf-8", "shift_jis", "cp932"]
    last_error = None

    for enc in encodings_to_try:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"CSVの読み込みに失敗しました（全ての文字コードで失敗）: {last_error}")


# ------------------------------------------------------------
# 4. 文字列の安全な取得
#
#    pandasはCSVの空欄を「NaN（float型）」として読み込むため、
#    そのまま str(値) とすると文字列 "nan" が入ってしまう不具合があった
#    （実データ検証で発覚：滋賀県だけで172件が汚染されていた）。
#    また、CSV内のURLに全角文字が混入しているケースがあったため
#    （実データ検証で発覚）、NFKCで半角に正規化する処理も追加する。
# ------------------------------------------------------------
def safe_str(value):
    """
    NaN（pandasの欠損値）を確実にNoneとして扱い、
    全角英数字・記号は半角に正規化した文字列を返す。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return text if text else None


# ------------------------------------------------------------
# 5. 電話番号・FAX番号の正規化
# ------------------------------------------------------------
def clean_phone(raw):
    """
    表示用の電話番号はそのまま活かしつつ、tel:リンク用に数字だけの
    文字列を別途生成する。
    """
    display = safe_str(raw)
    if not display:
        return None, None

    digits_only = re.sub(r"[^\d]", "", display)
    if not digits_only:
        return None, None

    return display, digits_only


# ------------------------------------------------------------
# 6. 利用可能曜日のパース
# ------------------------------------------------------------
def parse_available_days(raw):
    """
    「平日,土曜日,日曜日,祝日」のようなカンマ区切り文字列を、
    フロント側で扱いやすいbool形式の辞書に変換する。
    """
    days = {"weekday": False, "saturday": False, "sunday": False, "holiday": False}

    if not raw or not isinstance(raw, str):
        return days

    tokens = [t.strip() for t in raw.split(",")]

    if "平日" in tokens:
        days["weekday"] = True
    if "土曜日" in tokens:
        days["saturday"] = True
    if "日曜日" in tokens:
        days["sunday"] = True
    if "祝日" in tokens:
        days["holiday"] = True

    return days


# ------------------------------------------------------------
# 7. 「利用可能曜日特記事項」からの24時間・緊急対応の簡易判定
#    ★注意：これはCSV内の自由記述からの推定であり、断定ではない。
#    フロント側でも「特記事項の記載に基づく参考情報」として扱うこと。
# ------------------------------------------------------------
NIGHT_EMERGENCY_KEYWORDS = ["24時間", "緊急"]

def detect_night_emergency_hint(remarks):
    if not remarks or not isinstance(remarks, str):
        return False
    return any(kw in remarks for kw in NIGHT_EMERGENCY_KEYWORDS)


# ------------------------------------------------------------
# 8. Colabリサーチ結果（specialty_result_kansai.json）からのタグ付与
#    ★注意：これはAIによるホームページ内容の推定であり、断定ではない。
#    サイト側には必ず「AI推定・要確認」の免責を併記すること。
#
#    👑 全国対応にあたっての補足：リサーチ未実施の都道府県の事業所は
#    そもそもこのJSONに存在しないため、下のロジックにより自動的に
#    全カテゴリNone（情報なし）として安全に出力される。ロジック自体の
#    変更は不要。
# ------------------------------------------------------------
SPECIALTY_CATEGORIES = ["mental", "medical_care", "pediatric", "rehabilitation"]

def build_specialty_tags(jigyosho_no, specialty_data):
    """
    事業所番号をキーにColabリサーチ結果を検索し、各カテゴリの
    status（specialized / mentioned /
