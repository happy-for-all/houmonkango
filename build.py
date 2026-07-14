# ============================================================
# 🌿 訪問看護ナビ（関西圏） build.py
#
# 目的：
#   ① 厚労省CSV（jigyosho_130.csv）から関西6府県のデータを抽出
#   ② Colabリサーチ結果（specialty_result_kansai.json）と事業所番号で
#      突き合わせ、精神科対応・医療的ケア対応・小児対応・リハビリ特化の
#      タグを付与
#   ③ 都道府県別の軽量JSONファイルに分割して dist/ に出力
#
# 前回プロジェクト（まごころ福祉施設ナビ／AandB）の設計思想を踏襲：
#   ・都道府県別分割でファイルを軽量化
#   ・ビルド前に dist/ を必ずクリアしてから再構築（安全な再ビルド）
#   ・データが無くても壊れない（null許容）安全設計
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
SPECIALTY_JSON_PATH = "specialty_result_kansai.json"   # Colabリサーチ結果（ルート直下）
OUTPUT_DIR = "dist"

# 対象は関西6府県のみ（今回の要望のスコープ）
KANSAI_PREFECTURES = {
    "大阪府": "osaka",
    "京都府": "kyoto",
    "兵庫県": "hyogo",
    "奈良県": "nara",
    "滋賀県": "shiga",
    "和歌山県": "wakayama",
}

# CSVの更新時点（厚労省ページの表記に合わせて手動で更新してください）
CSV_SOURCE_LABEL = "2025年12月末時点（厚労省公表）"


# ------------------------------------------------------------
# 3. CSV読み込み（文字コード自動判定・AandBのロジックを踏襲）
# ------------------------------------------------------------
def load_csv_with_encoding_fallback(path):
    """
    複数の文字コードを順に試し、読み込めたものを採用する。
    jigyosho_130.csvは基本的にutf-8-sigだが、万一の文字コード違いに
    備えてAandBと同じ防御的な実装にしておく。
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
# 4. 文字列の安全な取得（★重要：実データ検証で見つかった不具合の修正★）
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
# ------------------------------------------------------------
SPECIALTY_CATEGORIES = ["mental", "medical_care", "pediatric", "rehabilitation"]

def build_specialty_tags(jigyosho_no, specialty_data):
    """
    事業所番号をキーにColabリサーチ結果を検索し、各カテゴリの
    status（specialized / mentioned / None）だけをフロント用に抽出する。
    リサーチ対象外（URLが無かった等）の場合は全カテゴリNoneのまま返す
    （＝「情報なし」として安全に表示される）。
    """
    tags = {cat: None for cat in SPECIALTY_CATEGORIES}

    entry = specialty_data.get(jigyosho_no)
    if not entry or entry.get("error") or not entry.get("tags"):
        return tags

    for cat in SPECIALTY_CATEGORIES:
        cat_result = entry["tags"].get(cat)
        if cat_result:
            tags[cat] = cat_result.get("status")  # "specialized" / "mentioned" / None

    return tags


# ------------------------------------------------------------
# 9. 1事業所分のレコードを組み立てる
# ------------------------------------------------------------
def build_url(raw_url):
    """
    全角文字混入・スキーム抜けを補正し、正しく開けるURLに整える。
    どうしても直せない・空欄の場合は None を返す（フロント側で
    「ホームページ情報なし」として扱われる）。
    """
    url = safe_str(raw_url)
    if not url:
        return None

    # "http:"や"https:"の直後に"//"が無いパターンを補正
    url = re.sub(r"^(https?):(?!//)", r"\1://", url)
    url = re.sub(r"^(https?)//", r"\1://", url)

    # スキームが無い場合は https:// を仮定する
    if not re.match(r"^https?://", url):
        url = "https://" + url

    return url


def build_station_record(row, specialty_data):
    jigyosho_no = safe_str(row.get("事業所番号")) or ""

    tel_display, tel_clean = clean_phone(row.get("電話番号"))
    fax_display, fax_clean = clean_phone(row.get("FAX番号"))

    address = safe_str(row.get("住所")) or ""
    # 👑 修正済み（2026-07-14）：実データ検証の結果、「方書（ビル名等）」列の内容は
    # 100%のケースで「住所」列に既に含まれていることが判明した（例：
    # 住所="...吉野四丁目10-22吉野Tビル2階" / 方書="吉野Tビル2階"）。
    # 以前はこれを単純に連結しており、ビル名が二重に表示される不具合があった。
    # 方書列は表示用には使わず、住所列をそのまま採用する。
    full_address = address

    try:
        lat = float(row.get("緯度"))
    except (TypeError, ValueError):
        lat = None
    try:
        lon = float(row.get("経度"))
    except (TypeError, ValueError):
        lon = None

    try:
        capacity = int(float(row.get("定員")))
    except (TypeError, ValueError):
        capacity = None

    record = {
        "jigyosho_no": jigyosho_no,
        "name": safe_str(row.get("事業所名")) or "",
        "name_kana": safe_str(row.get("事業所名カナ")) or "",
        "corporation_name": safe_str(row.get("法人の名称")) or "",
        "prefecture": row.get("都道府県名"),
        "city": row.get("市区町村名"),
        "address": full_address,
        "lat": lat,
        "lon": lon,
        "tel": tel_display,
        "tel_clean": tel_clean,
        "fax": fax_display,
        "fax_clean": fax_clean,
        # 👑 修正済み（2026-07-14）：以前はCSVのURLをそのまま使っており、
        # 全角文字混入URL（実データ検証で発覚）がそのまま出力されていた。
        # build_url()で半角正規化・スキーム補完を行うように修正。
        "url": build_url(row.get("URL")),
        "capacity": capacity,
        "available_days": parse_available_days(row.get("利用可能曜日")),
        "remarks": safe_str(row.get("利用可能曜日特記事項")),
        "night_emergency_hint": detect_night_emergency_hint(row.get("利用可能曜日特記事項")),
        "specialty_tags": build_specialty_tags(jigyosho_no, specialty_data),
    }

    return record


# ------------------------------------------------------------
# 10. メインのビルド処理
# ------------------------------------------------------------
def main():
    print("==========================================")
    print("🌿 訪問看護ナビ（関西圏） ビルド開始")
    print("==========================================")

    # 👑 安全な再ビルドのため、既存のdist/を必ず一度クリアする（AandBと同じ方針）
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # --- CSV読み込み ---
    df = load_csv_with_encoding_fallback(CSV_PATH)
    print(f"CSV読み込み完了：全国{len(df)}件")

    df_kansai = df[df["都道府県名"].isin(KANSAI_PREFECTURES.keys())].copy()
    print(f"関西6府県に絞り込み：{len(df_kansai)}件")

    # --- Colabリサーチ結果の読み込み ---
    if os.path.exists(SPECIALTY_JSON_PATH):
        with open(SPECIALTY_JSON_PATH, "r", encoding="utf-8") as f:
            specialty_data = json.load(f)
        print(f"特化情報リサーチ結果を読み込み：{len(specialty_data)}件分")
    else:
        # 👑 ファイルが無くてもビルド自体は止めない（安全設計）。
        # その場合、全事業所の specialty_tags はNone（情報なし）になる。
        specialty_data = {}
        print("⚠️ specialty_result_kansai.json が見つからないため、特化タグ無しでビルドします")

    # --- 都道府県別にレコードを構築 ---
    manifest = {
        "csv_source": CSV_SOURCE_LABEL,
        "specialty_research_count": len(specialty_data),
        "prefectures": {},
        "total_count": 0,
    }

    for pref_name, pref_slug in KANSAI_PREFECTURES.items():
        df_pref = df_kansai[df_kansai["都道府県名"] == pref_name]

        records = [build_station_record(row, specialty_data) for _, row in df_pref.iterrows()]

        output_path = os.path.join(OUTPUT_DIR, f"data_{pref_slug}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        manifest["prefectures"][pref_slug] = {
            "name": pref_name,
            "count": len(records),
        }
        manifest["total_count"] += len(records)

        print(f"  {pref_name}（{pref_slug}）：{len(records)}件 → {output_path}")

    # --- マニフェストの出力 ---
    manifest_path = os.path.join(OUTPUT_DIR, "data_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 👑 重要：CF Workerのassets配信は wrangler.json の "directory": "./dist"
    # 配下のファイルのみを対象とするため、index.html（および将来のfavicon.ico等の
    # 静的ファイル）も必ずdist/にコピーする必要がある。
    # これを忘れると、本番環境でindex.htmlからdata_*.jsonへの相対パスでの
    # fetch()が届かず、画面が「データを読み込み中です…」のまま止まってしまう
    # （実際にローカルで動作検証していて発覚した不具合）。
    static_files_to_copy = ["index.html"]
    for filename in static_files_to_copy:
        if os.path.exists(filename):
            shutil.copy(filename, os.path.join(OUTPUT_DIR, filename))
            print(f"  静的ファイルをコピー：{filename} → {OUTPUT_DIR}/{filename}")
        else:
            print(f"  ⚠️ {filename} が見つからないため、コピーをスキップしました")

    print("==========================================")
    print(f"✅ ビルド完了：合計{manifest['total_count']}件")
    print(f"マニフェスト：{manifest_path}")
    print("==========================================")


# ------------------------------------------------------------
# 11. 実行
# ------------------------------------------------------------
if __name__ == "__main__":
    main()
